import logging
import os
import time
import asyncio
import aiohttp  # <-- Use aiohttp
import io
import json
from utils.helpers import parse_move_command, has_significant_difference
# websockets is not used in this file, so it can be removed if not needed elsewhere.

class Klipper:
    def __init__(self, parent):
        # Corrected typo: __init__ instead of __init_
        # Corrected typo: self.parent = parent
        self.parent = parent

    async def printer_connection(self):
        # Create a single session that is reused for all requests in this loop
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    logging.info("[KLIPPER] Pulling data from Moonraker")
                    # Perform GET request for printer status
                    url = f"{self.parent.printer_url}/printer/objects/query?extruder&heater_bed&print_stats&virtual_sdcard"
                    async with session.get(url, timeout=10) as response:
                        response.raise_for_status()
                        printer_data = await response.json()

                    result = printer_data.get('result', {})
                    status = result.get('status', {})

                    temp_updates = {}

                    extruder = status.get('extruder', {})
                    temp_updates['nozzle_temperature'] = extruder.get('temperature', 0.0)
                    temp_updates['nozzle_temperature_target'] = extruder.get('target', 0.0)

                    heater_bed = status.get('heater_bed', {})
                    temp_updates['bed_temperature'] = heater_bed.get('temperature', 0.0)
                    temp_updates['bed_temperature_target'] = heater_bed.get('target', 0.0)

                    print_stats = status.get('print_stats', {})
                    virtual_sdcard = status.get('virtual_sdcard', {})

                    klipper_state = print_stats.get('state', '').lower()

                    state_map = {
                        'printing': ('printing', 'Printing'),
                        'paused': ('paused', 'Paused'),
                        'complete': ('complete', 'Complete'),
                        'standby': ('operational', 'Operational'),
                        'error': ('error', 'Error'),
                    }
                    temp_updates['status'], temp_updates['job_state'] = state_map.get(klipper_state, (klipper_state, klipper_state.capitalize()))

                    temp_updates['file_name'] = print_stats.get('filename')
                    temp_updates['progress'] = virtual_sdcard.get('progress', 0.0) * 100
                    temp_updates['print_time'] = print_stats.get('print_duration', 0.0)

                    if temp_updates['progress'] > 0 and temp_updates['print_time'] > 0:
                        time_left = (temp_updates['print_time'] / temp_updates['progress']) * (100 - temp_updates['progress'])
                        temp_updates['print_time_left'] = time_left
                    else:
                        temp_updates['print_time_left'] = 0.0

                    update_needed = False
                    for key, new_value in temp_updates.items():
                        old_value = self.parent.updates.get(key)
                        if has_significant_difference(key, old_value, new_value):
                            self.parent.updates[key] = new_value
                            update_needed = True

                    if update_needed:
                        self.parent.update_data_changed = True
                        logging.info(f"Update data changed flagged as True")

                    logging.info(f"Got data from API, printer status is: {temp_updates['status']}")

                except aiohttp.ClientResponseError as e:
                    if e.status == 409:
                        logging.warning("409 Conflict Error: Printer is busy or disconnected. Retrying in 10 seconds.")
                        self.parent.updates['status'] = 'error'
                        self.parent.update_data_changed = True
                        await self.reconnect_printer()
                        await asyncio.sleep(10)
                        continue
                    else:
                        logging.error(f"HTTP Error: {e.status} - {e.message}")
                except Exception as e:
                    self.parent.updates['status'] = 'error'
                    self.parent.update_data_changed = True
                    logging.error("Error connecting to Moonraker: %s", e)

                await asyncio.sleep(self.parent.reconnect_interval)

    async def send_command(self, command):
        payload = {"script": command}
        url = f"{self.parent.printer_url}/printer/gcode/script"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    response.raise_for_status()
                    logging.info("Command executed successfully: %s", command)
                    await self.parent.send_printer_ready()
        except aiohttp.ClientError as e:
            logging.error("Error executing command: %s", e)

    def _save_file_to_disk(self, file_content, file_path):
        """Synchronous helper to run blocking disk I/O in an executor."""
        logging.info(f"Saving file to {file_path}")
        with open(file_path, 'wb') as f:
            f.write(file_content)
        logging.info(f"File saved successfully.")

    async def print_file(self, filename, url):
        try:
            start_time = time.time()
            logging.info('Starting file transfer process from %s', url)
            download_headers = {'User-Agent': 'Mozilla/5.0 (compatible; PiPrinter/1.0)'}

            self.parent.uploading_file_progress = 0.0
            self.parent.update_data_changed = True

            async with aiohttp.ClientSession() as session:
                # 1. Asynchronously download the file into a memory buffer
                file_stream = io.BytesIO()
                async with session.get(url, headers=download_headers, timeout=60) as file_response:
                    file_response.raise_for_status()
                    total_size = int(file_response.headers.get('content-length', 0))
                    bytes_downloaded = 0
                    last_log_time = time.time()

                    async for chunk in file_response.content.iter_chunked(1024 * 1024 * 4): # 4MB chunks
                        file_stream.write(chunk)
                        bytes_downloaded += len(chunk)
                        if total_size > 0:
                            self.parent.uploading_file_progress = (bytes_downloaded / total_size) * 100
                            self.parent.update_data_changed = True

                        current_time = time.time()
                        if current_time - last_log_time > 5:
                            speed = bytes_downloaded / (current_time - start_time) / 1024 / 1024 if (current_time - start_time) > 0 else 0
                            logging.info(f'Downloaded {bytes_downloaded/(1024*1024):.1f}MB of {total_size/(1024*1024):.1f}MB ({speed:.2f} MB/s)')
                            last_log_time = current_time

                download_time = time.time() - start_time
                logging.info('Download completed in %.2f seconds', download_time)

                # 2. Save the file to disk using an executor to avoid blocking
                filename_safe = os.path.basename(filename)
                gcodes_dir = f"/home/{self.parent.username}/printer_data/gcodes"
                os.makedirs(gcodes_dir, exist_ok=True)
                file_path = os.path.join(gcodes_dir, filename_safe)

                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._save_file_to_disk, file_stream.getvalue(), file_path)

                # 3. Asynchronously tell the printer to start printing the file
                upload_start = time.time()
                print_url = f"{self.parent.printer_url}/printer/print/start"
                print_payload = {"filename": filename_safe}
                async with session.post(print_url, json=print_payload) as print_response:
                    print_response.raise_for_status()
                    response_text = await print_response.text()

                self.parent.updates['cancelled'] = None
                upload_time = time.time() - upload_start
                total_time = time.time() - start_time
                logging.info('Download: %.2fs, Upload/Save: %.2fs, Total: %.2fs', download_time, upload_time, total_time)
                logging.info('File transfer successful, print started: %s', response_text)

        except aiohttp.ClientError as e:
            logging.error('Network operation failed: %s', e)
        except IOError as e:
            logging.error(f'Failed during disk operation: {e}')
        finally:
            self.parent.uploading_file_progress = None
            self.parent.update_data_changed = True

        await self.parent.send_printer_ready()

    async def stop_print(self):
        url = f"{self.parent.printer_url}/printer/print/cancel"
        try:
            logging.info('Stopping print')
            async with aiohttp.ClientSession() as session:
                async with session.post(url) as response:
                    response.raise_for_status()
                    logging.info('Successfully stopped print')
                    await self.parent.send_printer_ready()
        except aiohttp.ClientError as e:
            logging.error('Stopping print failed: %s', e)

    async def reconnect_printer(self):
        url = f"{self.parent.printer_url}/printer/restart"
        try:
            logging.info('Reconnecting printer')
            async with aiohttp.ClientSession() as session:
                async with session.post(url) as response:
                    response.raise_for_status()
                    await self.parent.send_printer_ready()
                    logging.info('Successfully sent reconnect command')
        except aiohttp.ClientError as e:
            logging.error('Reconnect failed: %s', e)

    async def pause_print(self):
        url = f"{self.parent.printer_url}/printer/print/pause"
        try:
            logging.info('Pausing Print')
            async with aiohttp.ClientSession() as session:
                async with session.post(url) as response:
                    response.raise_for_status()
                    logging.info('Successfully paused print')
        except aiohttp.ClientError as e:
            logging.error('Pausing print failed: %s', e)

    async def resume_print(self):
        url = f"{self.parent.printer_url}/printer/print/resume"
        try:
            logging.info('Resuming Print')
            async with aiohttp.ClientSession() as session:
                async with session.post(url) as response:
                    response.raise_for_status()
                    logging.info('Successfully resumed print')
        except aiohttp.ClientError as e:
            logging.error('Resuming print failed: %s', e)

    async def move_extruder(self, x, y, z):
        url = f"{self.parent.printer_url}/printer/gcode/script"
        gcode_command = f"G91\nG1 X{x} Y{y} Z{z} F1000\nG90"
        payload = {"script": gcode_command}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    response.raise_for_status()
                    logging.info(f"Successfully moved extruder X:{x} Y:{y} Z:{z}")
                    await self.parent.send_printer_ready()
        except aiohttp.ClientError as e:
            logging.error(f"Failed to move extruder: {e}")

    async def set_temperatures(self, tool_temp: int, bed_temp: int):
        url = f"{self.parent.printer_url}/printer/gcode/script"
        try:
            async with aiohttp.ClientSession() as session:
                # Set extruder temp
                extruder_command = f"M104 S{tool_temp}"
                extruder_payload = {"script": extruder_command}
                async with session.post(url, json=extruder_payload) as r1:
                    r1.raise_for_status()
                    logging.info(f"Successfully set tool temperature to {tool_temp}°C")

                # Set bed temp
                bed_command = f"M140 S{bed_temp}"
                bed_payload = {"script": bed_command}
                async with session.post(url, json=bed_payload) as r2:
                    r2.raise_for_status()
                    logging.info(f"Successfully set bed temperature to {bed_temp}°C")
            await self.parent.send_printer_ready()
        except aiohttp.ClientError as e:
            logging.error(f"Failed to set temperatures: {e}")