import logging
import os
import time
import requests
import websockets
import asyncio
import io
import json

async def printer_connection(self):
    while True:
        try:
            # printer data
            response = requests.get(f"{self.printer_url}/printer/objects/query?extruder&heater_bed&print_stats&virtual_sdcard")
            response.raise_for_status()
            printer_data = response.json()
            
            result = printer_data.get('result', {})
            status = result.get('status', {})
            
            # initiate data update object
            temp_updates = {}
            
            # get values
            extruder = status.get('extruder', {})
            temp_updates['nozzle_temperature'] = extruder.get('temperature', 0.0)
            temp_updates['nozzle_temperature_target'] = extruder.get('target', 0.0)
            
            heater_bed = status.get('heater_bed', {})
            temp_updates['bed_temperature'] = heater_bed.get('temperature', 0.0)
            temp_updates['bed_temperature_target'] = heater_bed.get('target', 0.0)
            
            print_stats = status.get('print_stats', {})
            virtual_sdcard = status.get('virtual_sdcard', {})
            
            # map state to octoprint states
            klipper_state = print_stats.get('state', '').lower()
            
            if klipper_state == 'printing':
                temp_updates['status'] = 'printing'
                temp_updates['job_state'] = 'Printing'
            elif klipper_state == 'paused':
                temp_updates['status'] = 'paused'
                temp_updates['job_state'] = 'Paused'
            elif klipper_state == 'complete':
                temp_updates['status'] = 'complete'
                temp_updates['job_state'] = 'Complete'
            elif klipper_state == 'standby':
                temp_updates['status'] = 'operational'
                temp_updates['job_state'] = 'Operational'
            elif klipper_state == 'error':
                temp_updates['status'] = 'error'
                temp_updates['job_state'] = 'Error'
            else:
                temp_updates['status'] = klipper_state
                temp_updates['job_state'] = klipper_state.capitalize()
            
            # print job details
            temp_updates['file_name'] = print_stats.get('filename')
            temp_updates['progress'] = virtual_sdcard.get('progress', 0.0) * 100
            temp_updates['print_time'] = print_stats.get('print_duration', 0.0)
            
            # calculate time left
            if temp_updates['progress'] > 0 and temp_updates['print_time'] > 0:
                time_left = (temp_updates['print_time'] / temp_updates['progress']) * (100 - temp_updates['progress'])
                temp_updates['print_time_left'] = time_left
            else:
                temp_updates['print_time_left'] = 0.0

            # --- Check for significant changes ---
            update_needed = False

            for key, new_value in temp_updates.items():
                old_value = self.updates.get(key)

                if self.has_significant_difference(key, old_value, new_value):
                    logging.info(f"Value for '{key}' changed significantly: {old_value} -> {new_value}")
                    self.updates[key] = new_value
                    update_needed = True

            if update_needed:
                self.update_data_changed = True
                logging.info(f"Update data changed flagged as True")

            logging.info(f"Got data from API, printer status is: {temp_updates['status']}")

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 409:
                logging.warning("409 Conflict Error: Printer is busy or disconnected. Retrying in 10 seconds.")
                self.updates['status'] = 'error'
                self.update_data_changed = True
                await self.reconnect_printer()
                await asyncio.sleep(10)
                continue  # skip this iteration but keep the loop running
            else:
                logging.error(f"HTTP Error: {e}")
        except Exception as e:
            self.updates['status'] = 'error'
            self.update_data_changed = True
            logging.error("Error connecting to Moonraker: %s", e)

        await asyncio.sleep(self.reconnect_interval)  # keep retrying


async def send_command(self, command):
    try:
        payload = {
            "script": command
        }
        url = f"{self.printer_url}/printer/gcode/script"
        response = requests.post(url, json=payload)
        response.raise_for_status()
        logging.info("Command executed successfully: %s", command)
    except requests.exceptions.RequestException as e:
        logging.error("Error executing command: %s", e)

async def print_file(self, filename, url):
    try:
        start_time = time.time()
        logging.info('Starting file transfer process from %s', url)
        
        download_headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; PiPrinter/1.0)'
        }
        
        # downlod in chunks with session to feed back to server
        self.uploading_file_progress = 0.0
        self.update_data_changed = True
        with requests.Session() as session:
            # download the file with optimized parameters
            with session.get(
                url, 
                stream=True, 
                headers=download_headers,
                timeout=60
            ) as file_response:
                file_response.raise_for_status()
                file_stream = io.BytesIO()
                
                # track download progress
                total_size = int(file_response.headers.get('content-length', 0))
                bytes_downloaded = 0
                last_log_time = time.time()
                
                for chunk in file_response.iter_content(chunk_size=1024 * 1024 * 4):  # 4MB chunks
                    if chunk:
                        file_stream.write(chunk)
                        bytes_downloaded += len(chunk)

                        if total_size > 0:
                            self.uploading_file_progress = (bytes_downloaded / total_size) * 100
                            self.update_data_changed = True
                        
                        # log progress every 5 seconds
                        current_time = time.time()
                        if current_time - last_log_time > 5:
                            speed = bytes_downloaded / (current_time - start_time) / 1024 / 1024
                            logging.info(f'Downloaded {bytes_downloaded/(1024*1024):.1f}MB of {total_size/(1024*1024):.1f}MB ({speed:.2f} MB/s)')
                            last_log_time = current_time
            
            download_time = time.time() - start_time
            logging.info('Download completed in %.2f seconds', download_time)
            
            # reset the file pointer
            file_stream.seek(0)
            
            # upload to printer
            upload_start = time.time()
            filename_safe = os.path.basename(filename)
            gcodes_dir = f"/home/{self.username}/printer_data/gcodes"
            if not os.path.exists(gcodes_dir):
                # try alternative locations
                if os.path.exists(f"/home/{self.username}/klipper_config/gcodes"):
                    gcodes_dir = f"/home/{self.username}/klipper_config/gcodes"
                else:
                    # create the directory
                    os.makedirs(gcodes_dir, exist_ok=True)
            
            file_path = os.path.join(gcodes_dir, filename_safe)
            with open(file_path, 'wb') as f:
                f.write(file_stream.getvalue())
            
            logging.info(f'File saved to {file_path}')
            
            # start printing file
            print_url = f"{self.printer_url}/printer/print/start"
            print_payload = {
                "filename": filename_safe
            }
            response = requests.post(print_url, json=print_payload)
            response.raise_for_status()

            response.raise_for_status()
            self.updates['cancelled'] = None
            
            upload_time = time.time() - upload_start
            total_time = time.time() - start_time
            self.uploading_file_progress = None
            logging.info('Download: %.2fs, Upload: %.2fs, Total: %.2fs', 
                        download_time, upload_time, total_time)
            logging.info('File transfer successful: %s', response.text)
            
    except requests.exceptions.RequestException as e:
        self.uploading_file_progress = None
        logging.error('File transfer failed: %s', e)
    
    await self.send_printer_ready()

async def stop_print(self):
    try:
        logging.info('Stopping print')
        url = f"{self.printer_url}/printer/print/cancel"
        response = requests.post(url)
        response.raise_for_status()
        logging.info('Successfully stopped print')
        await self.send_printer_ready()
    except Exception as e:
        logging.error('Stopping print failed: %s', e)

async def reconnect_printer(self):
    try:
        logging.info('Reconnecting printer')
        url = f"{self.printer_url}/printer/restart"
        response = requests.post(url)
        response.raise_for_status()
        logging.info('Successfully sent reconnect command')
    except Exception as e:
        logging.error('Reconnect failed: %s', e)

async def pause_print(self):
    try:
        logging.info('Pausing Print')
        url = f"{self.printer_url}/printer/print/pause"
        response = requests.post(url)
        response.raise_for_status()
        logging.info('Successfully paused print')
    except Exception as e:
        logging.error('Pausing print failed: %s', e)

async def resume_print(self):
    try:
        logging.info('Resuming Print')
        url = f"{self.printer_url}/printer/print/resume"
        response = requests.post(url)
        response.raise_for_status()
        logging.info('Successfully resumed print')
    except Exception as e:
        logging.error('Resuming print failed: %s', e)
        
async def move_extruder(self, x, y, z):
        try:
            gcode_command = f"G91\nG1 X{x} Y{y} Z{z} F1000\nG90"
            payload = {
                "script": gcode_command
            }
            url = f"{self.printer_url}/printer/gcode/script"
            response = requests.post(url, json=payload)
            response.raise_for_status()
            logging.info(f"Successfully moved extruder X:{x} Y:{y} Z:{z}")
            await self.send_printer_ready()
        except Exception as e:
            logging.error(f"Failed to move extruder: {e}")

async def set_temperatures(self, tool_temp: int, bed_temp: int):
    try:
        url = f"{self.printer_url}/printer/gcode/script"

        # set extruder temp
        extruder_command = f"M104 S{tool_temp}"
        extruder_payload = {
            "script": extruder_command
        }
        response = requests.post(url, json=extruder_payload)
        response.raise_for_status()
        logging.info(f"Successfully set tool temperature to {tool_temp}°C")

        # set bed temp
        bed_command = f"M140 S{bed_temp}"
        bed_payload = {
            "script": bed_command
        }
        response = requests.post(url, json=bed_payload)
        response.raise_for_status()
        logging.info(f"Successfully set bed temperature to {bed_temp}°C")
        await self.send_printer_ready()
    except Exception as e:
        logging.error(f"Failed to set temperatures: {e}")
    
