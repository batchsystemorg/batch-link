import logging
import time
import websockets
import asyncio
import aiohttp  # Use aiohttp instead of requests
import io
import json
from utils.helpers import parse_move_command, has_significant_difference

class Octoprint:
    def __init__(self, parent):
        self.parent = parent  # Reference to BatchPrinterConnect
        self.terminal_buffer = []  # Buffer to store terminal output lines
        self.terminal_buffer_lock = asyncio.Lock()  # Thread-safe access to buffer
        self.session_key = None  # Store session key for WebSocket auth
        self.username = None  # Store username for WebSocket auth

    async def get_session_key(self):
        """Get session key for WebSocket authentication using API key"""
        try:
            login_url = f"{self.parent.printer_url}/api/login"
            # Use passive login with API key
            async with aiohttp.ClientSession() as session:
                async with session.post(login_url, json={"passive": True}, headers=self.parent.headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        self.session_key = data.get("session")
                        self.username = data.get("name", "api")  # Use "api" as default username
                        logging.info(f"Successfully obtained session key for user: {self.username}")
                        return True
                    else:
                        logging.error(f"Failed to get session key: {response.status}")
                        return False
        except Exception as e:
            logging.error(f"Error getting session key: {e}")
            return False

    async def printer_connection(self):
        octoprint_url = self.parent.printer_url + "/api/"
        logging.info(f"Executing printer_connection function")
        
        # Create a single session that is reused for all requests in this loop
        async with aiohttp.ClientSession(headers=self.parent.headers) as session:
            while True:
                try:
                    logging.info(f"[PRINTER] Pull data")

                    # Perform GET request for printer status
                    async with session.get(octoprint_url + 'printer', timeout=10) as response_printer:
                        response_printer.raise_for_status()
                        printer_info = await response_printer.json()

                    temp_updates = {}
                    temp_updates['status'] = printer_info.get('state', {}).get('text', 'unknown').lower()
                    temp_updates['bed_temperature'] = printer_info.get('temperature', {}).get('bed', {}).get('actual', 0.0)
                    temp_updates['nozzle_temperature'] = printer_info.get('temperature', {}).get('tool0', {}).get('actual', 0.0)
                    temp_updates['bed_temperature_target'] = printer_info.get('temperature', {}).get('bed', {}).get('target', 0.0)
                    temp_updates['nozzle_temperature_target'] = printer_info.get('temperature', {}).get('tool0', {}).get('target', 0.0)

                    # Perform GET request for job status
                    async with session.get(octoprint_url + 'job', timeout=10) as response_job:
                        response_job.raise_for_status()
                        printer_job = await response_job.json()

                    temp_updates['job_state'] = printer_job.get('state', None)
                    temp_updates['job_error'] = printer_job.get('error', None)
                    temp_updates['file_name'] = printer_job.get('job', {}).get('file', {}).get('name', None)
                    temp_updates['progress'] = printer_job.get('progress', {}).get('completion', 0.0)
                    temp_updates['print_time'] = printer_job.get('progress', {}).get('printTime', 0.0)
                    temp_updates['print_time_left'] = printer_job.get('progress', {}).get('printTimeLeft', 0.0)

                    # Add terminal output to updates if available
                    async with self.terminal_buffer_lock:
                        if self.terminal_buffer:
                            temp_updates['terminal_output'] = self.terminal_buffer.copy()
                            self.terminal_buffer.clear()  # Clear buffer after copying

                    update_needed = False
                    for key, new_value in temp_updates.items():
                        old_value = self.parent.updates.get(key)
                        if has_significant_difference(key, old_value, new_value):
                            self.parent.updates[key] = new_value
                            update_needed = True

                    if update_needed:
                        self.parent.update_data_changed = True

                    logging.info(f"[PRINTER] Data received: {temp_updates['status']}")

                except aiohttp.ClientResponseError as e:
                    if e.status == 409:
                        logging.warning("409 Conflict Error: Printer is busy or disconnected. Retrying in 10 seconds.")
                        self.parent.updates['status'] = 'error'
                        self.parent.update_data_changed = True
                        await self.reconnect_printer() # Note: reconnect_printer is now async
                        await asyncio.sleep(10)
                        continue
                    else:
                        logging.error(f"HTTP Error: {e.status} - {e.message}")
                except Exception as e:
                    logging.error("Error connecting to OctoPrint: %s", e)

                await asyncio.sleep(self.parent.reconnect_interval)

    async def print_file(self, filename, url):
        upload_headers = {'X-Api-Key': self.parent.octo_api_key}
        download_headers = {'User-Agent': 'Mozilla/5.0 (compatible; PiPrinter/1.0)'}
        
        try:
            start_time = time.time()
            logging.info('Starting file transfer process from %s', url)
            
            self.parent.uploading_file_progress = 0.0
            self.parent.update_data_changed = True

            async with aiohttp.ClientSession() as session:
                # 1. Download the file asynchronously
                async with session.get(url, headers=download_headers, timeout=60) as file_response:
                    file_response.raise_for_status()
                    
                    file_stream = io.BytesIO()
                    total_size = int(file_response.headers.get('content-length', 0))
                    bytes_downloaded = 0
                    last_log_time = time.time()
                    
                    # Asynchronously iterate over chunks
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
                
                file_stream.seek(0)
                
                # 2. Upload the file asynchronously using FormData
                upload_start = time.time()
                data = aiohttp.FormData()
                data.add_field('file', file_stream, filename=filename, content_type='application/octet-stream')
                data.add_field('print', 'true')
                
                upload_url = self.parent.printer_url + '/api/files/local'
                async with session.post(upload_url, data=data, headers=upload_headers, timeout=300) as response:
                    response.raise_for_status()
                    self.parent.updates['cancelled'] = None
                    response_text = await response.text()
                
                upload_time = time.time() - upload_start
                total_time = time.time() - start_time
                logging.info('Download: %.2fs, Upload: %.2fs, Total: %.2fs', download_time, upload_time, total_time)
                logging.info('File transfer successful: %s', response_text)
                
        except aiohttp.ClientError as e:
            logging.error('File transfer failed: %s', e)
        finally:
            self.parent.uploading_file_progress = None
            self.parent.update_data_changed = True

        await self.parent.send_printer_ready()
        
    async def send_command(self, command):
        payload = {"command": command}
        url = f"{self.parent.printer_url}/api/printer/command"
        try:
            async with aiohttp.ClientSession(headers=self.parent.headers) as session:
                async with session.post(url, json=payload, timeout=15) as response:
                    response.raise_for_status()
                    logging.info("Command executed successfully: %s", command)
                    await self.parent.send_printer_ready()
        except aiohttp.ClientError as e:
            logging.info("Error executing command: %s", e)
            await self.parent.send_printer_ready()
    
    async def emergency_stop(self):
        # the API accepts either "command" or "commands" (an array) — use the array form
        payload = {
            # "commands": [
            #     "M104 S0",  # hotend off
            #     "M140 S0",  # bed off
            #     "M106 S0",  # fans off
            #     "M84"       # steppers off
            # ]
            "command": 'M112'  
        }
        url = f"{self.parent.printer_url}/api/printer/command"
        try:
            async with aiohttp.ClientSession(headers=self.parent.headers) as session:
                async with session.post(url, json=payload, timeout=15) as response:
                    response.raise_for_status()
                    logging.info("Emergency stop sequence sent")
                    await self.parent.send_printer_ready()
        except aiohttp.ClientError as e:
            logging.error("Failed to send emergency stop: %s", e)
            await self.parent.send_printer_ready()


    async def stop_print(self):
        url = f"{self.parent.printer_url}/api/job"
        payload = {'command': 'cancel'}
        try:
            logging.info('Stopping print')
            async with aiohttp.ClientSession(headers=self.parent.headers) as session:
                async with session.post(url, json=payload, timeout=15) as response:
                    response.raise_for_status()
                    logging.info('Successfully stopped print')
                    await self.parent.send_printer_ready()
        except aiohttp.ClientError as e:
            logging.info('Stopping print failed: %s', e)
            await self.parent.send_printer_ready()

    async def reconnect_printer(self):
        url = f"{self.parent.printer_url}/api/connection"
        payload = {"command": "connect", "port": "AUTO"}
        try:
            logging.info('Reconnecting')
            async with aiohttp.ClientSession(headers=self.parent.headers) as session:
                async with session.post(url, json=payload) as response:
                    if response.status < 300:
                        logging.info(f"Response from reconnecting {response.status}")
        except aiohttp.ClientError as e:
            logging.info('Reconnecting printer failed: %s', e)

    async def pause_print(self):
        url = f"{self.parent.printer_url}/api/job"
        payload = {'command': 'pause', 'action': 'pause'}
        try:
            logging.info('Pausing Print')
            async with aiohttp.ClientSession(headers=self.parent.headers) as session:
                async with session.post(url, json=payload) as response:
                    if response.status < 300:
                        logging.info('Successfully paused print')
        except aiohttp.ClientError as e:
            logging.info('Pausing print failed: %s', e)

    async def resume_print(self):
        url = f"{self.parent.printer_url}/api/job"
        payload = {'command': 'pause', 'action': 'resume'}
        try:
            logging.info('Resuming Print')
            async with aiohttp.ClientSession(headers=self.parent.headers) as session:
                async with session.post(url, json=payload) as response:
                    if response.status < 300:
                        logging.info('Successfully resumed print')
        except aiohttp.ClientError as e:
            logging.info('Resuming print failed: %s', e)

    async def move_extruder(self, x, y, z):
        url = f"{self.parent.printer_url}/api/printer/printhead"
        payload = {"command": "jog", "x": x, "y": y, "z": z, "speed": 1000}
        try:
            async with aiohttp.ClientSession(headers=self.parent.headers) as session:
                async with session.post(url, json=payload) as response:
                    response.raise_for_status()
                    logging.info("Successfully executed move Extruder command")
                    await self.parent.send_printer_ready()
        except aiohttp.ClientError as e:
            logging.error(f"Failed to move extruder: {e}")

    async def set_temperatures(self, tool_temp: int, bed_temp: int):
        tool_url = f"{self.parent.printer_url}/api/printer/tool"
        bed_url = f"{self.parent.printer_url}/api/printer/bed"
        tool_payload = {"command": "target", "targets": {"tool0": tool_temp}}
        bed_payload = {"command": "target", "target": bed_temp}
        try:
            async with aiohttp.ClientSession(headers=self.parent.headers) as session:
                async with session.post(tool_url, json=tool_payload) as tool_response:
                    tool_response.raise_for_status()
                    logging.info(f"Successfully set tool temperature to {tool_temp}°C")
                
                async with session.post(bed_url, json=bed_payload) as bed_response:
                    bed_response.raise_for_status()
                    logging.info(f"Successfully set bed temperature to {bed_temp}°C")

            await self.parent.send_printer_ready()
        except aiohttp.ClientError as e:
            logging.error(f"Failed to set temperatures: {e}")
                
    async def listen_to_printer_push_api(self):
        # Try with port 5000 first, then fallback to port 80
        ws_url = "ws://localhost:5000/sockjs/websocket"
        while True:
            try:
                # First, get a session key
                if not self.session_key:
                    logging.info("Getting session key for WebSocket authentication...")
                    if not await self.get_session_key():
                        logging.error("Failed to get session key, retrying in 10 seconds...")
                        await asyncio.sleep(10)
                        continue
                
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                    logging.info(f"Connected to OctoPrint Push API at {ws_url}")

                    # 1) AUTH - Use username:session_key format as per docs
                    auth_msg = {"auth": f"{self.username}:{self.session_key}"}
                    await ws.send(json.dumps(auth_msg))
                    logging.info(f"Sent auth payload for user: {self.username}")

                    # 2) SUBSCRIBE (correct syntax!)
                    sub_msg = {
                        "subscribe": {
                            "state": { "logs": True, "messages": False },
                            "events": ["GcodeSending", "GcodeSent"]
                        }
                    }
                    await ws.send(json.dumps(sub_msg))
                    logging.info("Subscribed to Gcode events and terminal logs.")

                    # 3) READ & PARSE
                    async for raw in ws:
                        logging.debug(f"[PUSH-API] Raw frame: {raw!r}")

                        # 1) Try parsing as plain JSON:
                        try:
                            parsed = json.loads(raw)
                            # If it’s a dict, wrap it; if list, leave as is
                            msgs = parsed if isinstance(parsed, list) else [parsed]
                        except json.JSONDecodeError:
                            # 2) Not plain JSON: handle SockJS frames
                            if raw == "o":      # open
                                continue
                            if raw == "h":      # heartbeat
                                continue
                            if raw.startswith("a"):
                                try:
                                    msgs = json.loads(raw[1:])
                                except json.JSONDecodeError as e:
                                    logging.error(f"Failed to decode SockJS array frame: {e}")
                                    continue
                            else:
                                logging.warning(f"[PUSH-API] Unhandled frame: {raw!r}")
                                continue

                        # 3) Process each message dict { "<type>": payload }
                        for msg in msgs:
                            # Each msg should be a single-key dict
                            if not isinstance(msg, dict) or len(msg) != 1:
                                logging.warning(f"[PUSH-API] Unexpected message shape: {msg}")
                                continue

                            mtype, payload = next(iter(msg.items()))
                            # └──> e.g. mtype=="connected" or "current" or "event" etc :contentReference[oaicite:0]{index=0}

                            if mtype in ("current", "history"):
                                # payload["logs"], payload["messages"]
                                logs = payload.get("logs", [])
                                if logs:
                                    async with self.terminal_buffer_lock:
                                        for line in logs:
                                            self.terminal_buffer.append(line.strip())
                                        # Keep buffer size manageable
                                        if len(self.terminal_buffer) > 500:
                                            self.terminal_buffer = self.terminal_buffer[-500:]
                                    logging.info(f"[PUSH-API] Added {len(logs)} terminal lines")
                                    for line in logs:
                                        logging.info(f"[PUSH-API][LOG] {line}")
                            elif mtype == "event":
                                event_name = payload.get("type")
                                data = payload.get("payload", {})
                                logging.info(f"[PUSH-API][EVENT] {event_name} → {data}")
                                if event_name in {"GcodeSending", "GcodeSent"} and (cmd := data.get("cmd")):
                                    self.parent.last_gcode_command = cmd
                                    logging.info(f"Last G-code ({event_name}): {cmd}")
                            else:
                                logging.debug(f"[PUSH-API] Other ({mtype}): {payload}")
                                

            except Exception as e:
                logging.error(f"[PUSH-API] Connection error: {e}")
                # Clear session key on connection error - might be expired
                self.session_key = None
                self.username = None
            logging.info("Reconnecting to Push API in 5 seconds…")
            await asyncio.sleep(5)