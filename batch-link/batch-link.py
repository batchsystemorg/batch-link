
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
                async with websockets.connect(self.remote_websocket_url) as websocket:
                    self.remote_websocket = websocket
                    await self.remote_on_open(websocket)
                    self.initialUpdatesValues()
                    async for message in websocket:
                        await self.remote_on_message(websocket, message)
                    
            except Exception as e:
                logging.info("Error connecting to remote server: %s", e)
                
            logging.info("Attempting to reconnect in: %s", self.reconnect_interval)
            await asyncio.sleep(self.reconnect_interval)

    async def remote_on_message(self, ws, message):
        logging.info("Received from remote: %s", message)
        data = json.loads(message)
        if 'action' in data and 'content' in data:
            if data['action'] == 'print':
                logging.info('Received print command for URL: %s', data['content']['url'])
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
                logging.info('Received command to execute: %s', data['content'])
                self.send_command(data['content'])  # New method to send G-code commands
            elif "move" in data['action']:
                logging.info("ACTION: %s", data['action'])
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
        octoprint_url = self.printer_url + "/api/printer"
        while True:
            try:
                response = requests.get(octoprint_url, headers=self.headers)
                response.raise_for_status()
                printer_info = response.json()

                logging.info("Printer Info Raw: ")
                logging.info(printer_info)

                # Process the printer state and temperature
                state = printer_info['state'].get('text', 'unknown')
                bed_temp = printer_info['temperature']['bed']['actual']
                nozzle_temp = printer_info['temperature']['tool0']['actual']

                logging.info("PRINTER BED TEMP, %s", bed_temp)

                self.updates['status'] = state.lower()

                
                self.updates['bed_temperature'] = bed_temp
                self.updates['nozzle_temperature'] = nozzle_temp

                await asyncio.sleep(5)  # Adjust the interval as needed
            except Exception as e:
                logging.info("Error connecting to OctoPrint: %s", e)
                await asyncio.sleep(self.reconnect_interval)

    # async def printer_on_message(self, ws, message):
    #     data = json.loads(message)
    #     method = data.get('method')
    #     params = data.get('params')
    #     if (method is not None) and (params is not None):
    #         if (method == 'notify_status_update') and self.remote_websocket:
    #             self.decode_updates(params)
    #             return

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
            'progress': None,
        }

    # def decode_updates(self, params):
    #     logging.info("Decode updates")
    #     for param in params:
    #         try:
    #             heater_bed = param.get('heater_bed')
    #             self.updates['bed_temperature'] = heater_bed.get('temperature')
    #         except Exception:
    #             pass
    #         try:
    #             extruder = param.get('extruder')
    #             self.updates['nozzle_temperature'] = extruder.get('temperature')
    #         except Exception:
    #             pass
    #         try:
    #             idle_state = param.get('idle_timeout')
    #             self.updates['status'] = idle_state.get('state').lower()
    #         except Exception:
    #             pass
    #         try:
    #             print_stats = param.get('print_stats')
    #             if print_stats:
    #                 self.updates['print_stats'] = print_stats
    #                 if print_stats.get('state') == 'cancelled':
    #                     self.updates['cancelled'] = True
    #                 virtual_sdcard = param.get('virtual_sdcard')
    #                 self.updates['progress'] = virtual_sdcard.get('progress')
    #         except Exception:
    #             pass

    async def get_job_data(self):
        octoprint_url = self.printer_url + "/api/job"

        while True:
            try:
                # Fetch the job data from OctoPrint
                response = requests.get(octoprint_url, headers=self.headers)
                response.raise_for_status()

                job_info = response.json()

                # Extract the completion percentage from the response
                progress = job_info['progress']
                completion = progress.get('completion', 0.0)  # Default to 0.0 if not available

                # Update the progress in self.updates
                self.updates['progress'] = completion
                logging.info(f"Print completion: {completion}%")

                # Sleep for the update interval before polling again
                await asyncio.sleep(self.update_interval)
                
            except Exception as e:
                logging.info(f"Error getting job data from OctoPrint: {e}")
                await asyncio.sleep(self.reconnect_interval)

    async def send_printer_update(self):
        while True:
            try:
                if any(value is not None for value in self.updates.values()):
                    msg = {
                        'action': 'printer_update',
                        'content': self.updates
                    }
                    serialised_json = json.dumps(msg)
                    self.updates['cancelled'] = None
                    await self.remote_websocket.send(serialised_json)
            except Exception as e:
                logging.info("Error sending updates to remote server: %s", e)
            await asyncio.sleep(self.update_interval)

def main():
    communicator = BatchPrinterConnect()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.gather(
        communicator.remote_connection(),
        communicator.printer_connection(),
        communicator.get_job_data(),
        communicator.send_printer_update()
    ))
    loop.close()

if __name__ == "__main__":
    main()
