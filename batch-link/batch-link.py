
import os
from datetime import datetime
import cv2
import asyncio
import configparser
import requests
import json
import io
import websockets
import re
import logging
import time

class BatchPrinterConnect:
    def __init__(self):
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
        username = os.environ.get('USER')
        self.config_file_path = f"/home/{username}/.octoprint/batch-link.cfg"
        self.config = configparser.ConfigParser()
        self.config.read(self.config_file_path)

        if not self.config:
            raise FileNotFoundError(f"Configuration file not found at {self.config_file_path}")
        
        self.reconnect_interval = int(self.config['connection_settings']['RECONNECT_INTERVAL'])
        self.remote_websocket_url = self.config['connection_settings']['REMOTE_WS_URL']
        self.octo_api_key = self.config['printer_details']['API_KEY'].strip()
        self.printer_url = 'http://localhost'
        self.uploading_file_progress = None
        self.uuid = self.config['printer_details']['UUID'].strip()
        self.update_data_changed = True

        ## ------- CAMERA ------- ##
        self.current_recording_folder = None
        try:
            self.camera = cv2.VideoCapture(0)
            if not self.camera.isOpened():
                logging.warning("Failed to open camera - camera may not be connected")
                self.camera = None
        except Exception as e:
            logging.warning(f"Could not initialize camera: {e}")
            self.camera = None

        self.last_status = None
        self.last_gcode_command = None

        self.headers = {
            'X-Api-Key': self.octo_api_key
        }

        try:
            response = requests.get(self.printer_url + '/api/printer', headers=self.headers)
            response.raise_for_status()
            printer_info = response.json()
            logging.info("printer_info, %s", printer_info)
            self.status = printer_info['state'].get('text', 'unknown')  # Get the printer status (e.g., "Operational")
        except Exception as e:
            logging.info('Something went wrong trying to get the initial state: %s', e)
            self.status = 'error'

        self.printer_connection_id = None
        self.initialUpdatesValues()
        self.update_interval = 2
        self.alive_interval = 10

        self.remote_websocket = None

        if not all([self.remote_websocket_url, self.printer_url, self.uuid]):
            raise ValueError("One or more configuration parameters are missing.")

    # ************* REMOTE *************** #
    async def remote_connection(self):
        while True:
            try:
                logging.info("Trying to connect to websocket with URL: %s", self.remote_websocket_url)
                async with websockets.connect(
                    self.remote_websocket_url,
                    ping_interval=20,
                    ping_timeout=20
                ) as websocket:
                    self.remote_websocket = websocket
                    logging.info(f"Successfully connected to the remote websocket")
                    await self.remote_on_open(websocket)
                    self.initialUpdatesValues()
                    async for message in websocket:
                        try:
                            await self.remote_on_message(websocket, message)
                        except Exception as e:
                            logging.error(f"Error processing message: {e}")
                    
            except websockets.exceptions.ConnectionClosedOK as e:
                logging.warning(f"Websocket connection closed normally: {e} (code: {e.code})")
            except websockets.exceptions.ConnectionClosedError as e:
                logging.error(f"Websocket connection closed with error: {e} (code: {e.code})")
            except Exception as e:
                logging.info("Error connecting to remote server: %s", e)
            
            self.remote_websocket = None
            logging.info("Attempting to reconnect in: %s seconds", self.reconnect_interval)
            await asyncio.sleep(self.reconnect_interval)

    async def remote_on_message(self, ws, message):
        data = json.loads(message)
        logging.info(f"Received from remote")
        logging.info(data)
        try:
            if 'action' in data and 'content' in data:
                if data['action'] == 'print':
                    logging.info(f"File name to print: {data['content']['file_name']}")
                    filename = data['content']['file_name']
                    url = data['content']['url']
                    await asyncio.to_thread(self.print_file, filename, url)
                elif data['action'] == 'stop_print':
                    logging.info('Received stop print command for URL')
                    self.stop_print()
                elif data['action'] == 'connect':
                    logging.info('Received reconnect command for URL')
                    self.reconnect_printer()
                elif data['action'] == 'pause_print':
                    logging.info('Received pause print command for URL')
                    self.pause_print()
                elif data['action'] == 'resume_print':
                    logging.info('Received resume print command for URL')
                    self.resume_print()
                elif data['action'] == 'cmd':
                    logging.info('Received command to execute')
                    self.send_command(data['content'])
                elif data['action'] == 'heat_printer':
                    logging.info('Receive heating command')
                    self.set_temperatures(215, 60)
                elif data['action'] == 'cool_printer':
                    logging.info('Receive heating command')
                    self.set_temperatures(0, 0)
                elif "move" in data['action']:
                    logging.info("ACTION")
                    x, y, z = self.parse_move_command(data['action'])
                    self.move_extruder(x, y, z)
                elif data['action'] == 'reboot_system':
                    logging.info('Received reboot command')
                    await asyncio.to_thread(self.reboot_system)
                else:
                    logging.info('Unknown Command')
        except Exception as e:
            logging.warning(f"Error decoding data {data}: {e}")

    async def remote_on_open(self, ws):
        logging.info("Remote connection opened")
        uuid_message = {
            "action": "auth",
            "content": self.uuid,
        }
        await ws.send(json.dumps(uuid_message))
        logging.info('Message sent: %s', uuid_message)

    # **** REBOOT SYSTEM **** #
    def reboot_system(self):
        try:
            logging.info("Executing system reboot command")
            
            self.status = 'Unresponsive'
            self.updates['status'] = 'Unresponsive'
            self.update_data_changed = True
            
            time.sleep(self.update_interval)
            
            result = os.system('sudo /sbin/shutdown -r now')
            
            if result == 0:
                logging.info("Reboot command executed successfully")
            else:
                logging.error(f"Reboot command failed with exit code: {result}")
                
        except Exception as e:
            logging.error(f"Failed to execute reboot: {e}")
    # ************* CAMERA *************** #
    def fetch_snapshot(self):
        try:
            response = requests.get(
                f"{self.printer_url}:8080/?action=snapshot",
                headers=self.headers,
                stream=True
            )
            response.raise_for_status()
            return response.content  # Returns the image as bytes
        except Exception as e:
            logging.error(f"Failed to fetch snapshot: {e}")
            return None
        
    async def capture_images(self):
        while True:
            if self.updates['status'] == 'printing' and self.last_status != 'printing':
                self.start_new_recording()
            elif self.updates['status'] != 'printing' and self.last_status == 'printing':
                self.current_recording_folder = None

            if self.current_recording_folder:
                # ret, frame = self.camera.read()
                # logging.info(f"Ret: {ret} and frame: {frame} from camera read")
                # if ret:
                #     timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                #     gcode_command = self.get_current_gcode_command()
                #     if gcode_command:
                #         filename = f"{gcode_command}_{timestamp}.jpg"
                #     else:
                #         filename = f"{timestamp}.jpg"
                #     image_path = os.path.join(self.current_recording_folder, filename)
                #     cv2.imwrite(image_path, frame)
                #     logging.info(f"Saved image: {image_path}")
                snapshot = self.fetch_snapshot()
                if snapshot:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    gcode_command = self.get_current_gcode_command()
                    if gcode_command:
                        filename = f"{gcode_command}_{timestamp}.jpg"
                    else:
                        filename = f"{timestamp}.jpg"
                    image_path = os.path.join(self.current_recording_folder, filename)
                    with open(image_path, "wb") as image_file:
                        image_file.write(snapshot)
                    logging.info(f"Saved image: {image_path}")

            self.last_status = self.updates['status']
            await asyncio.sleep(2)  # Capture images every second

    def start_new_recording(self):
        # Create a new folder for the recording
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_recording_folder = os.path.expanduser(f"~/printer-image-data/{timestamp}")
        os.makedirs(self.current_recording_folder, exist_ok=True)
        logging.info(f"Started new recording in folder: {self.current_recording_folder}")

    async def listen_to_printer_push_api(self):
        ws_url = f"ws://localhost/sockjs/websocket"  # Or wss if HTTPS

        while True:
            try:
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                    logging.info(f"Connected to OctoPrint Push API at {ws_url}")

                    # Step 1: Authenticate
                    auth_payload = json.dumps({
                        "auth": self.octo_api_key
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
                                        self.last_gcode_command = cmd
                                        logging.info(f"[PUSH-API] Last G-code command ({event_name}): {cmd}")

                        except json.JSONDecodeError as e:
                            logging.error(f"JSON decode error: {e}")

            except Exception as e:
                logging.error(f"[PUSH-API] Connection error: {e}")

            logging.info("Reconnecting to Push API in 5 seconds...")
            await asyncio.sleep(5)

    
    def get_current_gcode_command(self):
        if self.last_gcode_command:
            return self.last_gcode_command
        else:
            logging.warning("No recent G-code command found. Returning 'unknown'.")
            return 'unknown'


    # ************* PRINTER *************** #
    def has_significant_difference(self, key, old_value, new_value):
        thresholds = {
            'bed_temperature': 0.7,
            'nozzle_temperature': 0.7,
        }

        if key in thresholds:
            threshold = thresholds[key]
            try:
                difference = abs(float(new_value) - float(old_value))
                return difference >= threshold
            except (ValueError, TypeError):
                return old_value != new_value
        else:
            return old_value != new_value
        
    async def printer_connection(self):
        octoprint_url = self.printer_url + "/api/"
        logging.info(f"Executing printer_connection function")
        while True:
            try:
                logging.info(f"[PRINTER] Pull data")
                response_printer = requests.get(
                    octoprint_url + 'printer', 
                    headers=self.headers, 
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
                    headers=self.headers,
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
                    old_value = self.updates.get(key)

                    if self.has_significant_difference(key, old_value, new_value):
                        # logging.info(f"Value for '{key}' changed significantly: {old_value} -> {new_value}")
                        self.updates[key] = new_value
                        update_needed = True

                if update_needed:
                    self.update_data_changed = True

                logging.info(f"[PRINTER] Data received: {temp_updates['status']}")

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 409:
                    logging.warning("409 Conflict Error: Printer is busy or disconnected. Retrying in 10 seconds.")
                    self.updates['status'] = 'error'
                    self.reconnect_printer()
                    self.update_data_changed = True
                    await asyncio.sleep(10)
                    continue  # Skip this iteration but keep the loop running
                else:
                    logging.error(f"HTTP Error: {e}")
            except Exception as e:
                logging.error("Error connecting to OctoPrint: %s", e)

            await asyncio.sleep(self.reconnect_interval)  # Keep retrying


    def send_command(self, command):
        try:
            # if command.lower() == 'reset':
                
            payload = {
                "command": command  # Send the command directly to OctoPrint
            }
            response = requests.post(
                f"{self.printer_url}/api/printer/command",
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            logging.info("Command executed successfully: %s", command)
            asyncio.create_task(self.send_printer_ready())
        except requests.exceptions.RequestException as e:
            logging.info("Error executing command: %s", e)

    def print_file(self, filename, url):
        headers = {
            'X-Api-Key': self.octo_api_key
        }
        
        try:
            start_time = time.time()
            logging.info('Starting file transfer process from %s', url)
            
            # Add a timeout and user-agent to improve download reliability
            download_headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; PiPrinter/1.0)'
            }
            
            # Use a session to maintain connection and improve download speed
            self.uploading_file_progress = 0.0
            self.update_data_changed = True
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
                                self.uploading_file_progress = (bytes_downloaded / total_size) * 100
                                self.update_data_changed = True
                            
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
                    self.printer_url + '/api/files/local', 
                    files=files, 
                    data=data, 
                    headers=headers
                )
                
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

    def stop_print(self):
        try:
            logging.info('Stopping print')
            response = requests.post(
                f"{self.printer_url}/api/job",
                headers=self.headers,
                json={'command': 'cancel'}
            )
            response.raise_for_status()
            logging.info('Successfully stopped print')
            asyncio.create_task(self.send_printer_ready())
        except Exception as e:
            logging.info('Stopping print failed: %s', e)

    def reconnect_printer(self):
        try:
            logging.info('Reconnecting')
            response = requests.post(
                f"{self.printer_url}/api/connection",
                headers=self.headers,
                json={
                    "command": "connect",
                    "port": "AUTO",
                }
            )
            if response:
                logging.info(f"Response from reconnecting {response}")
        except Exception as e:
            logging.info('Stopping print failed: %s', e)

    def pause_print(self):
        try:
            logging.info('Pausing Print')
            response = requests.post(
                f"{self.printer_url}/api/job",
                headers=self.headers,
                json={'command': 'pause', 'action': 'pause'}
            )
            if response:
                logging.info('Successfully paused print')
        except requests.exceptions.RequestException as e:
            logging.info('Pausing print failed: %s', e)

    def resume_print(self):
        try:
            logging.info('Resuming Print')
            response = requests.post(
                f"{self.printer_url}/api/job",
                headers=self.headers,
                json={'command': 'pause', 'action': 'resume'}
            )
            if response:
                logging.info('Successfully resumed print')
        except requests.exceptions.RequestException as e:
            logging.info('Resuming print failed: %s', e)

    def parse_move_command(self, action_string):
        # Use a regex to extract x, y, and z values
        match = re.findall(r'[xyz]:-?\d+', action_string)
        move_values = {}
        
        # Iterate through the matches and assign the values to x, y, z
        for m in match:
            axis, value = m.split(":")
            move_values[axis] = int(value)  # Convert value to int (or float if needed)
        
        # Now you have the x, y, and z values as a dictionary
        x = move_values.get('x', 0)  # Default to 0 if not provided
        y = move_values.get('y', 0)  # Default to 0 if not provided
        z = move_values.get('z', 0)  # Default to 0 if not provided
        
        return x, y, z

    def move_extruder(self, x, y, z):
        payload = {
            "command": "jog",
            "x": x,        # Move 10mm in the X direction
            "y": y,         # Move 5mm in the Y direction
            "z": z,        # Move -2mm in the Z direction
            "speed": 1000,  # Speed of the movement (optional)
        }

        # Send the command to move the printhead
        response = requests.post(
            f"{self.printer_url}/api/printer/printhead",
            headers=self.headers,
            json=payload
        )
        
        response.raise_for_status()
        logging.info("Successfully executed move Extruder command")
        asyncio.create_task(self.send_printer_ready())

    def set_temperatures(self, tool_temp: int, bed_temp: int):
        try:
            tool_payload = {"command": "target", "targets": {"tool0": tool_temp}}
            tool_response = requests.post(
                f"{self.printer_url}/api/printer/tool",
                headers=self.headers,
                json=tool_payload
            )
            tool_response.raise_for_status()
            logging.info(f"Successfully set tool temperature to {tool_temp}°C")

            bed_payload = {"command": "target", "target": bed_temp}
            bed_response = requests.post(
                f"{self.printer_url}/api/printer/bed",
                headers=self.headers,
                json=bed_payload
            )
            bed_response.raise_for_status()
            logging.info(f"Successfully set bed temperature to {bed_temp}°C")
            asyncio.create_task(self.send_printer_ready())
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to set temperatures: {e}")

    def initialUpdatesValues(self):
        self.updates = {
            'bed_temperature': None,
            'nozzle_temperature': None,
            'bed_temperature_target': None,
            'nozzle_temperature_target': None,
            'status': self.status,
            'print_stats': {
                "filename": None,
                "total_duration": None,
                "print_duration": None,
                "state": None,
                "message": None
            },
            'cancelled': None,
            'job_state': None,
            'job_error': None,
            'file_name': None,
            'progress': None,
            'print_time': None,
            'print_time_left': None,
            'uploading_file_progress': None,
        }

        self.update_data_changed = True

    async def send_printer_update(self):
        last_sent_time = time.time()
        while True:
            logging.info(f"[UPDATE] Called")
            try:
                time_since_last = time.time() - last_sent_time
                if any(value is not None for value in self.updates.values()) and self.remote_websocket is not None:
                    if not self.update_data_changed and time_since_last < 120:
                        await asyncio.sleep(self.update_interval)
                        continue
                    
                    logging.info(f"[UPDATE] Sending update, printer status: {self.updates['status']}")
                    msg = {
                        'action': 'printer_update',
                        'content': self.updates
                    }
                    serialised_json = json.dumps(msg)
                    self.updates['cancelled'] = None
                    self.updates['uploading_file_progress'] = self.uploading_file_progress
                    await self.remote_websocket.send(serialised_json)

                    self.update_data_changed = False
                    last_sent_time = time.time()
                else:
                    logging.warning(f"[UPDATE] Either the websocket isnt initialised or a value is None")

            except websockets.exceptions.ConnectionClosed as e:
                logging.info(f"[UPDATE] Websocket error, connection closed: {e}")
                self.remote_websocket = None
            except Exception as e:
                logging.info(f"[PRINTER-UPDATE] Error: {e}")
            
            await asyncio.sleep(self.update_interval)

    async def send_printer_alive(self):
        while True:
            logging.info(f"[ALIVE] Called")
            try:
                if self.remote_websocket is not None:
                    msg = {
                            'action': 'printer_alive',
                            'content': {} 
                    }
                    serialised_json = json.dumps(msg)
                    logging.info(f"[ALIVE] Sending")
                    await self.remote_websocket.send(serialised_json)
                else:
                    logging.warning(f"[ALIVE] Either the websocket isnt initialised or a value is None")

            except websockets.exceptions.ConnectionClosed as e:
                logging.info(f"[ALIVE] Websocket error, connection closed: {e}")
                self.remote_websocket = None
            except Exception as e:
                logging.info(f"[ALIVE] Error: {e}")

            await asyncio.sleep(self.alive_interval)
    
    async def send_printer_ready(self):
        if self.remote_websocket is not None:
            try:
                msg = {
                    'action': 'printer_ready',
                    'content': {}
                }
                await self.remote_websocket.send(json.dumps(msg))
                logging.info('Sent printer_ready update')
            except Exception as e:
                logging.warning(f"Failed to send printer_ready: {e}")
        else:
            logging.warning("WebSocket not connected — cannot send printer_ready")



def main():
    communicator = BatchPrinterConnect()
    loop = asyncio.get_event_loop()
    tasks = asyncio.gather(
        communicator.remote_connection(),
        communicator.printer_connection(),
        communicator.send_printer_update(),
        communicator.send_printer_alive(),
        # communicator.capture_images(),
        # communicator.listen_to_printer_push_api(),
        return_exceptions=True
    )
    loop.run_until_complete(tasks)
    loop.close()


if __name__ == "__main__":
    main()
