import signal
import os
from datetime import datetime
# import cv2
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
        self.version = 0.7
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
        self.username = os.environ.get('USER')
        self.config_file_path = f"/home/{self.username}/moonraker/batch-link-klipper.cfg"
        self.config = configparser.ConfigParser()
        self.config.read(self.config_file_path)

        if not self.config.sections():
            raise FileNotFoundError(f"Configuration file not found at {self.config_file_path}")
        
        self.reconnect_interval = int(self.config['connection_settings']['RECONNECT_INTERVAL'])
        self.remote_websocket_url = self.config['connection_settings']['REMOTE_WS_URL']
        
        self.moonraker_port = int(self.config.get('printer_details', 'MOONRAKER_PORT', fallback='7125'))
        self.printer_url = f'http://localhost:{self.moonraker_port}'
        
        if not self.is_moonraker_running():
            logging.error("Moonraker is not running at %s. Please check your installation.", self.printer_url)
            raise ConnectionError("Cannot connect to Moonraker")
        
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

         # get initial printer status
        try:
            response = requests.get(f"{self.printer_url}/printer/info")
            response.raise_for_status()
            printer_info = response.json()
            logging.info("printer_info: %s", printer_info)
            self.status = printer_info.get('result', {}).get('state', 'unknown')
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
        
    def is_moonraker_running(self):
        try:
            response = requests.get(f"{self.printer_url}/server/info", timeout=5)
            if response.status_code == 200:
                logging.info("Moonraker is running at %s", self.printer_url)
                return True
            return False
        except requests.exceptions.RequestException:
            return False

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
                    await self.send_printer_ready()
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
        if 'action' in data and 'content' in data:
            if data['action'] == 'print':
                logging.info(f"File name to print: {data['content']['file_name']}")
                filename = data['content']['file_name']
                url = data['content']['url']
                await self.send_printer_busy()
                await self.print_file(filename, url)
            elif data['action'] == 'stop_print':
                logging.info('Received stop print command for URL')
                await self.send_printer_busy()
                await self.stop_print()
            elif data['action'] == 'connect':
                logging.info('Received reconnect command for URL')
                await self.reconnect_printer()
            elif data['action'] == 'pause_print':
                logging.info('Received pause print command for URL')
                await self.pause_print()
            elif data['action'] == 'resume_print':
                logging.info('Received resume print command for URL')
                await self.resume_print()
            elif data['action'] == 'cmd':
                logging.info('Received command to execute')
                await self.send_printer_busy()
                await self.send_command(data['content'])
            elif data['action'] == 'heat_printer':
                logging.info('Receive heating command')
                await self.set_temperatures(215, 60)
            elif data['action'] == 'cool_printer':
                logging.info('Receive heating command')
                await self.set_temperatures(0, 0)
            elif "move" in data['action']:
                logging.info("ACTION")
                x, y, z = self.parse_move_command(data['action'])
                await self.move_extruder(x, y, z)
            elif data['action'] == 'reboot_system':
                logging.info('Received reboot command')
                await self.send_printer_busy()
                await self.reboot_system()

            else:
                logging.info('Unknown Command')

    async def remote_on_open(self, ws):
        logging.info("Remote connection opened")
        uuid_message = {
            "action": "auth",
            "content": self.uuid,
        }
        await ws.send(json.dumps(uuid_message))
        logging.info('Message sent: %s', uuid_message)

    # **** REBOOT SYSTEM **** #
    async def reboot_system(self):
        try:
            logging.info("Executing system reboot command")
            
            self.status = 'Unresponsive'
            self.updates['status'] = 'Unresponsive'
            self.update_data_changed = True
            
            await asyncio.sleep(self.update_interval)
            
            result = os.system('sudo /sbin/shutdown -r now')
            
            if result == 0:
                logging.info("Reboot command executed successfully")
            else:
                logging.error(f"Reboot command failed with exit code: {result}")
                
        except Exception as e:
            logging.error(f"Failed to execute reboot: {e}")
    # ************* CAMERA *************** #
   

    
    def get_current_gcode_command(self):
        if self.last_gcode_command:
            return self.last_gcode_command
        else:
            logging.warning("No recent G-code command found. Returning 'unknown'.")
            return 'unknown'


    # ************* PRINTER *************** #


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
            logging.info(f"[VERSION] {self.version}")
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
    
    async def send_printer_busy(self):
        if self.remote_websocket is not None:
            try:
                msg = {
                    'action': 'printer_busy',
                    'content': {}
                }
                await self.remote_websocket.send(json.dumps(msg))
                logging.info('Sent printer_busy update')
            except Exception as e:
                logging.warning(f"Failed to send printer_busy: {e}")
        else:
            logging.warning("WebSocket not connected — cannot send printer_busy")
            
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

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, loop.stop)

    try:
        tasks = asyncio.gather(
            communicator.remote_connection(),
            communicator.printer_connection(),
            communicator.send_printer_update(),
            communicator.send_printer_alive(),
        )
        loop.run_until_complete(tasks)
    finally:
        loop.close()


if __name__ == "__main__":
    main()
