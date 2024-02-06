import asyncio
import configparser
import requests
import json
import io
import websockets

class BatchPrinterConnect:
    def __init__(self):
        self.config_file_path = '/home/pi/printer_data/config/batch-server.cfg'
        self.config = configparser.ConfigParser()
        self.config.read(self.config_file_path)

        if not self.config:
            raise FileNotFoundError(f"Configuration file not found at {self.config_file_path}")
        
        self.reconnect_interval = int(self.config['connection_settings']['RECONNECT_INTERVAL'])
        self.remote_websocket_url = self.config['connection_settings']['REMOTE_WS_URL']
        self.printer_websocket_url = self.config['connection_settings']['MOONRAKER_WS_URL']
        self.printer_url = self.config['connection_settings']['PRINTER_URL']
        self.uuid = self.config['printer_details']['UUID']

        try:
            response = requests.get(self.printer_url + '/printer/info')
            response.raise_for_status()

            result = json.loads(response.text).get('result')
            status = result.get('state')
        except Exception as e:
            print('Something went wrong trying to get the initial state: ', e)

        self.updates = {
            'bed_temperature': None,
            'nozzle_temperature': None,
            'status': status,
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

        self.update_interval = 5

        self.remote_websocket = None

        if not all([self.remote_websocket_url, self.printer_websocket_url, self.printer_url, self.uuid]):
            raise ValueError("One or more configuration parameters are missing.")

    # ************* REMOTE *************** #
    async def remote_connection(self):
        while True:
            try:
                async with websockets.connect(self.remote_websocket_url) as websocket:
                    self.remote_websocket = websocket
                    await self.remote_on_open(websocket)
                    async for message in websocket:
                        await self.remote_on_message(websocket, message)
                    
            except Exception as e:
                print(f"Error connecting to remote server: {e}")
            print(f"Attempting to reconnect in {self.reconnect_interval} seconds...")
            await asyncio.sleep(self.reconnect_interval)

    async def remote_on_message(self, ws, message):
        print(f"Received from remote: {message}")
        data = json.loads(message)
        if 'action' in data and 'content' in data:
            if data['action'] == 'print':
                print('Received print command for URL: ', data['content']['url'])
                filename = data['content']['file_name']
                url = data['content']['url']
                self.print_file(filename, url)
            else:
                print('Unknown Command')

    async def remote_on_open(self, ws):
        print("Remote connection opened")
        uuid_message = {
            "action": "auth",
            "content": self.uuid,
        }
        await ws.send(json.dumps(uuid_message))
        print('Message sent: ', uuid_message)

    # ************* PRINTER *************** #
    async def printer_connection(self):
        while True:
            try:
                async with websockets.connect(self.printer_websocket_url) as websocket:
                    await self.printer_on_open(websocket)
                    async for message in websocket:
                        await self.printer_on_message(websocket, message)
            except Exception as e:
                print(f"Error connecting to printer moonraker server: {e}")
            print(f"Attempting to reconnect to printer in {self.reconnect_interval} seconds...")
            await asyncio.sleep(self.reconnect_interval)

    # Define printer_on_message, printer_on_error, printer_on_close, printer_on_open similarly
    async def printer_on_message(self, ws, message):
        data = json.loads(message)
        method = data.get('method')
        params = data.get('params')
        if (method is not None) and (params is not None):
            if (method == 'notify_status_update') and self.remote_websocket:
                print('Params from moonraker before decoding them: ', params)
                self.decode_updates(params)
                return

    async def printer_on_open(self, ws):
        print("Connection to printer opened")
        subscription_message = json.dumps({
            "jsonrpc": "2.0",
            "method": "printer.objects.subscribe",
            "params": {
                "objects": {
                    "toolhead": ["position", "status"],
                    "extruder": ["target", "temperature"],
                    "idle_timeout": ["state", "printing_time"],
                    "heater_bed": ["target", "temperature"],
                    "print_stats": ["filename", "total_duration", "print_duration", "state", "message"],
                    "virtual_sdcard": ["progress"]
                }
            },
            "id": 1234
        })

        # await ws.send(printer_subscribtion)
        await ws.send(subscription_message)

    # ************* PRINTER HTTP *************** #
    def print_file(self, filename, url):
        try:
            print('trying to upload file with url: ', url)
            file_response = requests.get(url)
            file_response.raise_for_status()

            file_stream = io.BytesIO(file_response.content)
            file_stream.seek(0)

            files = {'file': (filename, file_stream)}
            data = {'print': 'true'}

            # Perform the file upload
            print('Trying to upload to printer URL: ', self.printer_url)
            response = requests.post(self.printer_url + '/server/files/upload', files=files, data=data)
            response.raise_for_status()
            self.updates['cancelled'] = None
            print('File transfer successful:', response.text)
        except requests.exceptions.RequestException as e:
            print('File transfer failed:', e)
    
    def decode_updates(self, params):
        for param in params:
            try:
                heater_bed = param.get('heater_bed')
                print('Heater Bed: ', heater_bed)
                bed_temperature = heater_bed.get('temperature')
                print('Heater bed temp: ', bed_temperature)
                self.updates['bed_temperature'] = bed_temperature
            except Exception as e:
                print('Param bed temp not part of this update')
            
            try:
                extruder = param.get('extruder')
                nozzle_temperature = extruder.get('temperature')
                self.updates['nozzle_temperature'] = nozzle_temperature
            except Exception as e:
                print('Param extruder temp not part of this update')

            try:
                idle_state = param.get('idle_timeout')
                state = idle_state.get('state')
                self.updates['status'] = state.lower()
            except Exception as e:
                print('Param idle_state not part of this update')

            try:
                print_stats = param.get('print_stats')
            except Exception as e:
                print('Param idle_state not part of this update')

            if print_stats is not None:
                self.updates['print_stats'] = print_stats
                cancelled = print_stats.get('state')
                if cancelled == 'cancelled':
                    self.updates['cancelled'] = True
            else:
                self.updates['print_stats'] = None

            try:
                virtual_sdcard = param.get('virtual_sdcard')
                progress = virtual_sdcard.get('progress')
                self.updates['progress'] = progress
            except Exception as e:
                print('Param progress couldnt be found')


    async def send_printer_update(self):
        while True:
            try:
                print('Updates before checking if filled: ', self.updates)
                if any(value is not None for value in self.updates.values()):
                    msg = {
                        'action': 'printer_update',
                        'content': self.updates
                    }
                    serialised_json = json.dumps(msg)
                    self.updates['cancelled'] = None
                    print('sending updates to API ', serialised_json)
                    await self.remote_websocket.send(serialised_json)

            except Exception as e:
                print(f"Error sending updates to remote server: {e}")

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
