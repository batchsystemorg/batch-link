
import os
import asyncio
import configparser
import requests
import json
import io
import websockets
import re
import logging

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
        self.uuid = self.config['printer_details']['UUID'].strip()

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
        self.update_interval = 5

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
                        await self.remote_on_message(websocket, message)
                    
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
        logging.info(f"Received from remote")
        data = json.loads(message)
        if 'action' in data and 'content' in data:
            if data['action'] == 'print':
                logging.info(f"File name to print: {data['content']['file_name']}")
                filename = data['content']['file_name']
                url = data['content']['url']
                self.print_file(filename, url)
            elif data['action'] == 'stop_print':
                logging.info('Received stop print command for URL')
                self.stop_print()
            elif data['action'] == 'pause_print':
                logging.info('Received pause print command for URL')
                self.pause_print()
            elif data['action'] == 'resume_print':
                logging.info('Received resume print command for URL')
                self.resume_print()
            elif data['action'] == 'cmd':
                logging.info('Received command to execute')
                self.send_command(data['content'])  # New method to send G-code commands
            elif "move" in data['action']:
                logging.info("ACTION")
                x, y, z = self.parse_move_command(data['action'])
                self.move_extruder(x, y, z)

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

    # ************* PRINTER *************** #
    async def printer_connection(self):
        octoprint_url = self.printer_url + "/api/"
        logging.info(f"Executing printer_connection function")
        while True:
            try:
                logging.info(f"Trying to get data from API")
                #### PRINTER DATA ###
                response_printer = requests.get(
                    octoprint_url + 'printer', 
                    headers=self.headers, 
                    timeout=10
                )
                response_printer.raise_for_status()
                printer_info = response_printer.json()

                # Process the printer state and temperature
                state = printer_info.get('state', {}).get('text', 'unknown')
                bed_temp = printer_info.get('temperature', {}).get('bed', {}).get('actual', 0.0)
                nozzle_temp = printer_info.get('temperature', {}).get('tool0', {}).get('actual', 0.0)

                self.updates['status'] = state.lower()
                self.updates['bed_temperature'] = bed_temp
                self.updates['nozzle_temperature'] = nozzle_temp

                #### JOB DATA ###
                response_job = requests.get(
                    octoprint_url + 'job', 
                    headers=self.headers,
                    timeout=10
                )
                response_job.raise_for_status()
                printer_job = response_job.json()

                # Process the job data
                job_error = printer_job.get('error', None)
                job_state = printer_job.get('state', None)
                progress = printer_job.get('progress', {}).get('completion', 0.0)
                file_name = printer_job.get('job', {}).get('file', {}).get('name', None)
                print_time = printer_job.get('progress', {}).get('printTime')
                if print_time is None:
                    print_time = 0.0
                print_time_left = printer_job.get('progress', {}).get('printTimeLeft')
                if print_time_left is None:
                    print_time_left = 0.0

                self.updates['job_state'] = job_state
                self.updates['job_error'] = job_error
                self.updates['file_name'] = file_name
                self.updates['progress'] = progress
                self.updates['print_time'] = print_time
                self.updates['print_time_left'] = print_time_left
                logging.info(f"Got data from API, printer status is: {state.lower()}")

                await asyncio.sleep(1)  # Adjust the interval as needed
            except Exception as e:
                logging.info("Error connecting to OctoPrint: %s", e)
                await asyncio.sleep(self.reconnect_interval)


    def send_command(self, command):
        try:
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
        except requests.exceptions.RequestException as e:
            logging.info("Error executing command: %s", e)
    def print_file(self, filename, url):
        headers = {
            'X-Api-Key': self.octo_api_key
        }
        try:
            logging.info('trying to upload file with url: %s', url)
            file_response = requests.get(url)
            file_response.raise_for_status()
            file_stream = io.BytesIO(file_response.content)
            file_stream.seek(0)
            files = {'file': (filename, file_stream)}
            data = {'print': 'true'}
            response = requests.post(self.printer_url + '/api/files/local', files=files, data=data, headers=headers)
            response.raise_for_status()
            self.updates['cancelled'] = None
            logging.info('File transfer successful: %s', response.text)
        except requests.exceptions.RequestException as e:
            logging.info('File transfer failed: %s', e)

    def stop_print(self):
        try:
            logging.info('Stopping print')
            response = requests.post(
                f"{self.printer_url}/api/job",
                headers=self.headers,
                json={'command': 'cancel'}
            )
            if response:
                logging.info('Successfully stopped print')
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

    def initialUpdatesValues(self):
        self.updates = {
            'bed_temperature': None,
            'nozzle_temperature': None,
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
        }

        self.update_data_changed = False

    async def send_printer_update(self):
        while True:
            logging.info(f"Executing sending printer updates function")
            try:
                if any(value is not None for value in self.updates.values()) and self.remote_websocket is not None:
                    if self.update_data_changed:
                        continue
                    
                    logging.info(f"Sending status within updates: {self.updates['status']}")
                    msg = {
                        'action': 'printer_update',
                        'content': self.updates
                    }
                    serialised_json = json.dumps(msg)
                    self.updates['cancelled'] = None
                    await self.remote_websocket.send(serialised_json)
                else:
                    logging.warning(f"Either the websocket isnt initialised or a value is None")

            except websockets.exceptions.ConnectionClosed as e:
                logging.info("Websocket was closed while sending printer updates: %s", e)
                self.remote_websocket = None
            except Exception as e:
                logging.info("Error sending updates to remote server: %s", e)
            
            await asyncio.sleep(self.update_interval)

def main():
    communicator = BatchPrinterConnect()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.gather(
        communicator.remote_connection(),
        communicator.printer_connection(),
        communicator.send_printer_update()
    ))
    loop.close()

if __name__ == "__main__":
    main()
