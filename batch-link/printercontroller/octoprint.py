import logging
import time
import requests
import websockets
import asyncio
import io
import json
from ..utils.helpers import parse_move_command, has_significant_difference

class Octoprint:
    def __init__(self, parent):
        self.parent = parent  # Reference to BatchPrinterConnect
        
    async def printer_connection(self):
        octoprint_url = self.parent.printer_url + "/api/"
        logging.info(f"Executing printer_connection function")
        while True:
            try:
                logging.info(f"[PRINTER] Pull data")
                response_printer = requests.get(
                    octoprint_url + 'printer', 
                    headers=self.parent.headers, 
                    timeout=10
                )
                response_printer.raise_for_status()
                printer_info = response_printer.json()

                temp_updates = {}
                temp_updates['status'] = printer_info.get('state', {}).get('text', 'unknown').lower()
                temp_updates['bed_temperature'] = printer_info.get('temperature', {}).get('bed', {}).get('actual', 0.0)
                temp_updates['nozzle_temperature'] = printer_info.get('temperature', {}).get('tool0', {}).get('actual', 0.0)
                temp_updates['bed_temperature_target'] = printer_info.get('temperature', {}).get('bed', {}).get('target', 0.0)
                temp_updates['nozzle_temperature_target'] = printer_info.get('temperature', {}).get('tool0', {}).get('target', 0.0)

                # Handle job info
                response_job = requests.get(
                    octoprint_url + 'job', 
                    headers=self.parent.headers,
                    timeout=10
                )
                response_job.raise_for_status()
                printer_job = response_job.json()

                temp_updates['job_state'] = printer_job.get('state', None)
                temp_updates['job_error'] = printer_job.get('error', None)
                temp_updates['file_name'] = printer_job.get('job', {}).get('file', {}).get('name', None)
                temp_updates['progress'] = printer_job.get('progress', {}).get('completion', 0.0)
                temp_updates['print_time'] = printer_job.get('progress', {}).get('printTime', 0.0)
                temp_updates['print_time_left'] = printer_job.get('progress', {}).get('printTimeLeft', 0.0)

                # --- Check for significant changes ---
                update_needed = False

                for key, new_value in temp_updates.items():
                    old_value = self.parent.updates.get(key)

                    if has_significant_difference(key, old_value, new_value):
                        # logging.info(f"Value for '{key}' changed significantly: {old_value} -> {new_value}")
                        self.parent.updates[key] = new_value
                        update_needed = True

                if update_needed:
                    self.parent.update_data_changed = True

                logging.info(f"[PRINTER] Data received: {temp_updates['status']}")

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 409:
                    logging.warning("409 Conflict Error: Printer is busy or disconnected. Retrying in 10 seconds.")
                    self.parent.updates['status'] = 'error'
                    self.parent.update_data_changed = True
                    await self.parent.reconnect_printer()
                    await asyncio.sleep(10)
                    continue  # Skip this iteration but keep the loop running
                else:
                    logging.error(f"HTTP Error: {e}")
            except Exception as e:
                logging.error("Error connecting to OctoPrint: %s", e)

            await asyncio.sleep(self.parent.reconnect_interval)  # Keep retrying


    async def print_file(self, filename, url):
        headers = {
            'X-Api-Key': self.parent.octo_api_key
        }
        
        try:
            start_time = time.time()
            logging.info('Starting file transfer process from %s', url)
            
            # Add a timeout and user-agent to improve download reliability
            download_headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; PiPrinter/1.0)'
            }
            
            # Use a session to maintain connection and improve download speed
            self.parent.uploading_file_progress = 0.0
            self.parent.update_data_changed = True
            with requests.Session() as session:
                # Download the file with optimized parameters
                with session.get(
                    url, 
                    stream=True, 
                    headers=download_headers,
                    timeout=60
                ) as file_response:
                    file_response.raise_for_status()
                    
                    # Use a BytesIO buffer to collect the data
                    file_stream = io.BytesIO()
                    
                    # Track download progress
                    total_size = int(file_response.headers.get('content-length', 0))
                    bytes_downloaded = 0
                    last_log_time = time.time()
                    
                    # Download with larger chunks to improve throughput
                    for chunk in file_response.iter_content(chunk_size=1024 * 1024 * 4):  # 4MB chunks
                        if chunk:
                            file_stream.write(chunk)
                            bytes_downloaded += len(chunk)

                            if total_size > 0:
                                self.parent.uploading_file_progress = (bytes_downloaded / total_size) * 100
                                self.parent.update_data_changed = True
                            
                            # Log progress every 5 seconds
                            current_time = time.time()
                            if current_time - last_log_time > 5:
                                speed = bytes_downloaded / (current_time - start_time) / 1024 / 1024
                                logging.info(f'Downloaded {bytes_downloaded/(1024*1024):.1f}MB of {total_size/(1024*1024):.1f}MB ({speed:.2f} MB/s)')
                                last_log_time = current_time
                
                download_time = time.time() - start_time
                logging.info('Download completed in %.2f seconds', download_time)
                
                # Reset the file pointer to the beginning
                file_stream.seek(0)
                
                # Upload to OctoPrint
                upload_start = time.time()
                files = {'file': (filename, file_stream)}
                data = {'print': 'true'}
                
                response = session.post(
                    self.parent.printer_url + '/api/files/local', 
                    files=files, 
                    data=data, 
                    headers=headers
                )
                
                response.raise_for_status()
                self.parent.updates['cancelled'] = None
                
                upload_time = time.time() - upload_start
                total_time = time.time() - start_time
                self.parent.uploading_file_progress = None
                logging.info('Download: %.2fs, Upload: %.2fs, Total: %.2fs', 
                            download_time, upload_time, total_time)
                logging.info('File transfer successful: %s', response.text)
                
        except requests.exceptions.RequestException as e:
            self.parent.uploading_file_progress = None
            logging.error('File transfer failed: %s', e)
        
        await self.parent.send_printer_ready()
        
    async def send_command(self, command):
        try:
            # if command.lower() == 'reset':
                
            payload = {
                "command": command  # Send the command directly to OctoPrint
            }
            response = requests.post(
                f"{self.parent.printer_url}/api/printer/command",
                headers=self.parent.headers,
                json=payload
            )
            response.raise_for_status()
            logging.info("Command executed successfully: %s", command)
            await self.parent.send_printer_ready()
        except requests.exceptions.RequestException as e:
            logging.info("Error executing command: %s", e)
        
        
    async def stop_print(self):
        try:
            logging.info('Stopping print')
            response = requests.post(
                f"{self.parent.printer_url}/api/job",
                headers=self.parent.headers,
                json={'command': 'cancel'}
            )
            response.raise_for_status()
            logging.info('Successfully stopped print')
            await self.parent.send_printer_ready()
        except Exception as e:
            logging.info('Stopping print failed: %s', e)

    async def reconnect_printer(self):
        try:
            logging.info('Reconnecting')
            response = requests.post(
                f"{self.parent.printer_url}/api/connection",
                headers=self.parent.headers,
                json={
                    "command": "connect",
                    "port": "AUTO",
                }
            )
            if response:
                logging.info(f"Response from reconnecting {response}")
        except Exception as e:
            logging.info('Stopping print failed: %s', e)

    async def pause_print(self):
        try:
            logging.info('Pausing Print')
            response = requests.post(
                f"{self.parent.printer_url}/api/job",
                headers=self.parent.headers,
                json={'command': 'pause', 'action': 'pause'}
            )
            if response:
                logging.info('Successfully paused print')
        except requests.exceptions.RequestException as e:
            logging.info('Pausing print failed: %s', e)

    async def resume_print(self):
        try:
            logging.info('Resuming Print')
            response = requests.post(
                f"{self.parent.printer_url}/api/job",
                headers=self.parent.headers,
                json={'command': 'pause', 'action': 'resume'}
            )
            if response:
                logging.info('Successfully resumed print')
        except requests.exceptions.RequestException as e:
            logging.info('Resuming print failed: %s', e)



    async def move_extruder(self, x, y, z):
        payload = {
            "command": "jog",
            "x": x,        # Move 10mm in the X direction
            "y": y,         # Move 5mm in the Y direction
            "z": z,        # Move -2mm in the Z direction
            "speed": 1000,  # Speed of the movement (optional)
        }

        # Send the command to move the printhead
        response = requests.post(
            f"{self.parent.printer_url}/api/printer/printhead",
            headers=self.parent.headers,
            json=payload
        )
        
        response.raise_for_status()
        logging.info("Successfully executed move Extruder command")
        await self.parent.send_printer_ready()

    async def set_temperatures(self, tool_temp: int, bed_temp: int):
        try:
            tool_payload = {"command": "target", "targets": {"tool0": tool_temp}}
            tool_response = requests.post(
                f"{self.parent.printer_url}/api/printer/tool",
                headers=self.parent.headers,
                json=tool_payload
            )
            tool_response.raise_for_status()
            logging.info(f"Successfully set tool temperature to {tool_temp}°C")

            bed_payload = {"command": "target", "target": bed_temp}
            bed_response = requests.post(
                f"{self.parent.printer_url}/api/printer/bed",
                headers=self.parent.headers,
                json=bed_payload
            )
            bed_response.raise_for_status()
            logging.info(f"Successfully set bed temperature to {bed_temp}°C")
            await self.parent.send_printer_ready()
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to set temperatures: {e}")
                
                
    async def listen_to_printer_push_api(self):
        ws_url = f"ws://localhost/sockjs/websocket"  # Or wss if HTTPS

        while True:
            try:
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                    logging.info(f"Connected to OctoPrint Push API at {ws_url}")

                    # Step 1: Authenticate
                    auth_payload = json.dumps({
                        "auth": self.parent.octo_api_key
                    })
                    await ws.send(auth_payload)
                    logging.info(f"Sent auth payload.")

                    # Step 2: Subscribe to Gcode events
                    subscribe_payload = json.dumps({
                        "command": "subscribe",
                        "data": {
                            "topics": ["event:GcodeSending", "event:GcodeSent"]
                        }
                    })
                    await ws.send(subscribe_payload)
                    logging.info(f"Subscribed to Gcode events.")

                    # Step 3: Listen for messages
                    async for message in ws:
                        logging.info(f"[PUSH-API] Raw message: {message}")

                        try:
                            data = json.loads(message)

                            # Event-based system
                            if data.get("type") == "event":
                                event_name = data.get("name")
                                payload = data.get("payload", {})

                                if event_name in ["GcodeSending", "GcodeSent"]:
                                    cmd = payload.get("cmd")
                                    if cmd:
                                        self.parent.last_gcode_command = cmd
                                        logging.info(f"[PUSH-API] Last G-code command ({event_name}): {cmd}")

                        except json.JSONDecodeError as e:
                            logging.error(f"JSON decode error: {e}")

            except Exception as e:
                logging.error(f"[PUSH-API] Connection error: {e}")

            logging.info("Reconnecting to Push API in 5 seconds...")
            await asyncio.sleep(5)