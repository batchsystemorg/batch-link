import logging
import time
import websockets
import asyncio
import aiohttp  # Use aiohttp for all HTTP interactions
import io
import json
from datetime import datetime
from utils.helpers import parse_move_command, has_significant_difference


class Octoprint:
    def __init__(self, parent):
        self.parent = parent  # Reference to BatchPrinterConnect
        self.terminal_buffer = []  # Buffer to store terminal output lines
        self.terminal_buffer_lock = asyncio.Lock()  # Thread-safe access to buffer
        self.session_key = None  # Store session key for WebSocket auth
        self.username = None  # Store username for WebSocket auth
        self.session: aiohttp.ClientSession | None = None  # Reusable HTTP session

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """
        Lazily initialize a single aiohttp.ClientSession for all requests.
        """
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers=self.parent.headers)
        return self.session

    async def close(self):
        """
        Cleanly close the HTTP session when shutting down.
        """
        if self.session and not self.session.closed:
            await self.session.close()

    async def get_session_key(self):
        """Get session key for WebSocket authentication using API key"""
        try:
            login_url = f"{self.parent.printer_url}/api/login"
            session = await self._ensure_session()
            async with session.post(login_url, json={"passive": True}) as response:
                if response.status == 200:
                    data = await response.json()
                    self.session_key = data.get("session")
                    self.username = data.get("name", "api")
                    logging.info(f"Successfully obtained session key for user: {self.username}")
                    return True
                else:
                    logging.error(f"Failed to get session key: {response.status}")
                    return False
        except Exception as e:
            logging.error(f"Error getting session key: {e}")
            return False

    async def printer_connection(self):
        """Poll OctoPrint for status updates in a loop"""
        octoprint_url = self.parent.printer_url + "/api/"
        session = await self._ensure_session()

        while True:
            try:
                logging.info("[PRINTER] Pull data")

                # Printer status
                async with session.get(octoprint_url + 'printer', timeout=10) as response_printer:
                    response_printer.raise_for_status()
                    printer_info = await response_printer.json()

                temp_updates = {
                    'status': printer_info.get('state', {}).get('text', 'unknown').lower(),
                    'bed_temperature': printer_info.get('temperature', {}).get('bed', {}).get('actual', 0.0),
                    'nozzle_temperature': printer_info.get('temperature', {}).get('tool0', {}).get('actual', 0.0),
                    'bed_temperature_target': printer_info.get('temperature', {}).get('bed', {}).get('target', 0.0),
                    'nozzle_temperature_target': printer_info.get('temperature', {}).get('tool0', {}).get('target', 0.0)
                }

                # Job status
                async with session.get(octoprint_url + 'job', timeout=10) as response_job:
                    response_job.raise_for_status()
                    printer_job = await response_job.json()

                temp_updates.update({
                    'job_state': printer_job.get('state'),
                    'job_error': printer_job.get('error'),
                    'file_name': printer_job.get('job', {}).get('file', {}).get('name'),
                    'progress': printer_job.get('progress', {}).get('completion', 0.0),
                    'print_time': printer_job.get('progress', {}).get('printTime', 0.0),
                    'print_time_left': printer_job.get('progress', {}).get('printTimeLeft', 0.0)
                })

                # Terminal output
                async with self.terminal_buffer_lock:
                    if self.terminal_buffer:
                        temp_updates['terminal_output'] = self.terminal_buffer.copy()
                        self.terminal_buffer.clear()

                # Check for significant changes
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
                    logging.warning("409 Conflict Error: Printer busy/disconnected. Retrying in 10s.")
                    self.parent.updates['status'] = 'error'
                    self.parent.update_data_changed = True
                    await self.reconnect_printer()
                    await asyncio.sleep(10)
                    continue
                else:
                    logging.error(f"HTTP Error: {e.status} - {e.message}")
            except Exception as e:
                logging.error("Error connecting to OctoPrint: %s", e)

            await asyncio.sleep(self.parent.reconnect_interval)

    async def print_file(self, filename, url):
        """Download a file from URL and upload to OctoPrint for printing"""
        upload_headers = {'X-Api-Key': self.parent.octo_api_key}
        download_headers = {'User-Agent': 'Mozilla/5.0 (compatible; PiPrinter/1.0)'}

        try:
            start_time = time.time()
            logging.info('Starting file transfer from %s', url)
            self.parent.uploading_file_progress = 0.0
            self.parent.update_data_changed = True

            session = await self._ensure_session()
            # Download
            async with session.get(url, headers=download_headers, timeout=60) as file_response:
                file_response.raise_for_status()
                file_stream = io.BytesIO()
                total_size = int(file_response.headers.get('content-length', 0))
                bytes_downloaded = 0
                last_log = time.time()

                async for chunk in file_response.content.iter_chunked(4 * 1024 * 1024):
                    file_stream.write(chunk)
                    bytes_downloaded += len(chunk)
                    if total_size:
                        self.parent.uploading_file_progress = (bytes_downloaded / total_size) * 100
                        self.parent.update_data_changed = True
                    if time.time() - last_log > 5:
                        speed = bytes_downloaded / (time.time() - start_time) / 1024 / 1024
                        logging.info(f'Downloaded {bytes_downloaded/(1024*1024):.1f}MB of {total_size/(1024*1024):.1f}MB ({speed:.2f} MB/s)')
                        last_log = time.time()

            download_time = time.time() - start_time
            logging.info('Download completed in %.2f seconds', download_time)
            file_stream.seek(0)

            # Upload
            upload_start = time.time()
            data = aiohttp.FormData()
            data.add_field('file', file_stream, filename=filename, content_type='application/octet-stream')
            data.add_field('print', 'true')

            upload_url = f"{self.parent.printer_url}/api/files/local"
            async with session.post(upload_url, data=data, headers=upload_headers, timeout=300) as response:
                response.raise_for_status()
                self.parent.updates['cancelled'] = None
                resp_text = await response.text()

            upload_time = time.time() - upload_start
            total = time.time() - start_time
            logging.info('Download: %.2fs, Upload: %.2fs, Total: %.2fs', download_time, upload_time, total)
            logging.info('File transfer successful: %s', resp_text)

        except aiohttp.ClientError as e:
            logging.error('File transfer failed: %s', e)
        finally:
            self.parent.uploading_file_progress = None
            self.parent.update_data_changed = True

        await self.parent.send_printer_ready()

    async def send_command(self, command):
        """Send a raw G-code command"""
        payload = {"command": command}
        url = f"{self.parent.printer_url}/api/printer/command"
        try:
            session = await self._ensure_session()
            async with session.post(url, json=payload, timeout=15) as response:
                response.raise_for_status()
                logging.info("Command executed: %s", command)
                await self.parent.send_printer_ready()
        except aiohttp.ClientError as e:
            logging.info("Error executing command: %s", e)
            await self.parent.send_printer_ready()

    async def emergency_stop(self):
        """Send M112 emergency stop"""
        payload = {"command": 'M112'}
        url = f"{self.parent.printer_url}/api/printer/command"
        try:
            session = await self._ensure_session()
            async with session.post(url, json=payload, timeout=15) as response:
                response.raise_for_status()
                logging.info("Emergency stop sequence sent")
                await self.parent.send_printer_ready()
        except aiohttp.ClientError as e:
            logging.error("Failed emergency stop: %s", e)
            await self.parent.send_printer_ready()

    async def stop_print(self):
        """Cancel current print job"""
        url = f"{self.parent.printer_url}/api/job"
        payload = {'command': 'cancel'}
        try:
            logging.info('Stopping print')
            session = await self._ensure_session()
            async with session.post(url, json=payload, timeout=15) as response:
                response.raise_for_status()
                logging.info('Print stopped')
                await self.parent.send_printer_ready()
        except aiohttp.ClientError as e:
            logging.info('Stopping print failed: %s', e)
            await self.parent.send_printer_ready()

    async def reconnect_printer(self):
        """Attempt to reconnect to printer"""
        url = f"{self.parent.printer_url}/api/connection"
        payload = {"command": "connect", "port": "AUTO"}
        try:
            logging.info('Reconnecting')
            session = await self._ensure_session()
            async with session.post(url, json=payload) as response:
                if response.status < 300:
                    logging.info(f"Reconnected with status {response.status}")
        except aiohttp.ClientError as e:
            logging.info('Reconnect failed: %s', e)

    async def pause_print(self):
        """Pause current print"""
        url = f"{self.parent.printer_url}/api/job"
        payload = {'command': 'pause', 'action': 'pause'}
        try:
            logging.info('Pausing print')
            session = await self._ensure_session()
            async with session.post(url, json=payload) as response:
                response.raise_for_status()
                logging.info('Print paused')
        except aiohttp.ClientError as e:
            logging.info('Pause failed: %s', e)

    async def resume_print(self):
        """Resume paused print"""
        url = f"{self.parent.printer_url}/api/job"
        payload = {'command': 'pause', 'action': 'resume'}
        try:
            logging.info('Resuming print')
            session = await self._ensure_session()
            async with session.post(url, json=payload) as response:
                response.raise_for_status()
                logging.info('Print resumed')
        except aiohttp.ClientError as e:
            logging.info('Resume failed: %s', e)

    async def move_extruder(self, x, y, z):
        """Jog the printhead by X/Y/Z"""
        url = f"{self.parent.printer_url}/api/printer/printhead"
        payload = {"command": "jog", "x": x, "y": y, "z": z, "speed": 1000}
        try:
            session = await self._ensure_session()
            async with session.post(url, json=payload) as response:
                response.raise_for_status()
                logging.info("Moved extruder to (%s, %s, %s)", x, y, z)
                await self.parent.send_printer_ready()
        except aiohttp.ClientError as e:
            logging.error(f"Failed to move extruder: {e}")

    async def set_temperatures(self, tool_temp: int, bed_temp: int):
        """Set hotend and bed temperatures"""
        tool_url = f"{self.parent.printer_url}/api/printer/tool"
        bed_url = f"{self.parent.printer_url}/api/printer/bed"
        tool_payload = {"command": "target", "targets": {"tool0": tool_temp}}
        bed_payload = {"command": "target", "target": bed_temp}
        try:
            session = await self._ensure_session()
            async with session.post(tool_url, json=tool_payload) as tool_resp:
                tool_resp.raise_for_status()
                logging.info(f"Set tool temp to {tool_temp}°C")
            async with session.post(bed_url, json=bed_payload) as bed_resp:
                bed_resp.raise_for_status()
                logging.info(f"Set bed temp to {bed_temp}°C")
            await self.parent.send_printer_ready()
        except aiohttp.ClientError as e:
            logging.error(f"Failed to set temperatures: {e}")

    async def listen_to_printer_push_api(self):
        """Connect to OctoPrint's WebSocket push API for live events/logs"""
        ws_url = "ws://localhost:5000/sockjs/websocket"
        while True:
            try:
                if not self.session_key:
                    logging.info("Getting session key for WebSocket auth…")
                    if not await self.get_session_key():
                        logging.error("Failed to get session key, retrying in 10s…")
                        await asyncio.sleep(10)
                        continue

                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                    logging.info(f"Connected to Push API at {ws_url}")

                    # AUTH
                    auth_msg = {"auth": f"{self.username}:{self.session_key}"}
                    await ws.send(json.dumps(auth_msg))
                    logging.info(f"Sent auth for user: {self.username}")

                    # SUBSCRIBE
                    sub_msg = {
                        "subscribe": {
                            "state": {"logs": True, "messages": False},
                            "events": ["GcodeSending", "GcodeSent"]
                        }
                    }
                    await ws.send(json.dumps(sub_msg))
                    logging.info("Subscribed to events/logs")

                    # READ LOOP
                    async for raw in ws:
                        try:
                            parsed = json.loads(raw)
                            msgs = parsed if isinstance(parsed, list) else [parsed]
                        except json.JSONDecodeError:
                            if raw in ("o", "h"):
                                continue
                            if raw.startswith("a"):
                                try:
                                    msgs = json.loads(raw[1:])
                                except json.JSONDecodeError:
                                    continue
                            else:
                                logging.warning(f"Unhandled frame: {raw!r}")
                                continue

                        for msg in msgs:
                            if not isinstance(msg, dict) or len(msg) != 1:
                                continue
                            mtype, payload = next(iter(msg.items()))

                            if mtype in ("current", "history"):
                                logs = payload.get("logs", [])
                                if logs:
                                    async with self.terminal_buffer_lock:
                                        for line in logs:
                                            if not line.strip().startswith("Recv: T:"):
                                                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                                self.terminal_buffer.append(f"[{ts}]: {line.strip()}")
                                        if len(self.terminal_buffer) > 500:
                                            self.terminal_buffer = self.terminal_buffer[-500:]
                                    logging.info(f"[PUSH-API] Added {len(logs)} lines")
                            elif mtype == "event":
                                event_name = payload.get("type")
                                data = payload.get("payload", {})
                                logging.info(f"[PUSH-API][EVENT] {event_name} → {data}")
                                if event_name in {"GcodeSending", "GcodeSent"}:
                                    cmd = data.get("cmd")
                                    if cmd:
                                        self.parent.last_gcode_command = cmd
                                        logging.info(f"Last G-code: {cmd}")
                            else:
                                logging.debug(f"[PUSH-API] Other ({mtype}): {payload}")

            except Exception as e:
                logging.error(f"[PUSH-API] Connection error: {e}")
                self.session_key = None
                self.username = None
            logging.info("Reconnecting to Push API in 5s…")
            await asyncio.sleep(5)
