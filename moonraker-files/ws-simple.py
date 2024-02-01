# --------------- BATCH WORKS API <-> MOONRAKER  --------------- #
import configparser
import websocket
import threading
import time
import requests
import json
import io


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

        if not all([self.remote_websocket_url, self.printer_websocket_url, self.printer_url, self.uuid]):
            raise ValueError("One or more configuration parameters are missing.")
        
        self.remote_connection_thread = threading.Thread(target=self.remote_connection)
        self.remote_connection_thread.start()

        self.printer_connection_thread = threading.Thread(target=self.printer_connection)
        self.printer_connection_thread.start()

    # --------------------------- REMOTE WEBSOCKT --------------------------- #
    def remote_on_message(self, ws, message):
        print(f"Received from remote: {message}")
        data = json.loads(message)
        if 'action' in data and 'content' in data:
            if data['action'] == 'print':
                print('Received print command for URL: ', data['content'])
                self.print_file(data['content'])
            else:
                print('Unknown Command')


    def remote_on_error(self, ws, error):
        print(f"Error remote: {error}")

    def remote_on_close(self, ws, close_status_code, close_msg):
        print(f"Connection remote closed with status code {close_status_code}: {close_msg}")

    def remote_on_open(self, ws):
        auth_message = {
            "action": "uuid",
            "content": self.uuid
        }
        ws.send(json.dumps(auth_message))
        print("Connection remote opened")

    def remote_connection(self):
        print('Triggering remote connection')
        while True:
            print('While true in remote connection')
            try:
                remote_ws = websocket.WebSocketApp(
                    self.remote_websocket_url,
                    on_open=self.remote_on_open,
                    on_message=self.remote_on_message,
                    on_error=self.remote_on_error,
                    on_close=self.remote_on_close
                )
                remote_thread = threading.Thread(target=remote_ws.run_forever)
                remote_thread.start()
                remote_thread.join()  # Wait for the WebSocket to close
            except Exception as e:
                print(f"Error connecting to remote server: {e}")

            print(f"Attempting to reconnect in {self.reconnect_interval} seconds...")
            time.sleep(self.reconnect_interval)

    # Start the remote connection in a separate thread
    


    # --------------------------- PRINTER WEBSOCKT --------------------------- #
    def printer_on_message(self, ws, message):
        # print(f"Received from printer: {message}")
        print('Incoming message from printer')

    def printer_on_error(self, ws, error):
        print(f"Error from printer: {error}")

    def printer_on_close(self, ws, close_status_code, close_msg):
        print(f"Connection closed with status code {close_status_code}: {close_msg}")

    def printer_on_open(self, ws):
        print("Connection to printer opened")

    def printer_connection(self):
        while True:
            print('While true in printer connection')
            try:
                printer_ws = websocket.WebSocketApp(self.printer_websocket_url, on_open=self.printer_on_open, on_message=self.printer_on_message, on_error=self.printer_on_error, on_close=self.printer_on_close)
                printer_thread = threading.Thread(target=printer_ws.run_forever)
                printer_thread.start()
                printer_thread.join()
            except Exception as e:
                print(f"Error connecting to printer moonraker server: {e}")

            print(f"Attempting to reconnect to printer in {self.reconnect_interval} seconds...")
            time.sleep(self.reconnect_interval)



    # --------------------------- POST REQUEST FUNCTIONALITY --------------------------- #

    def print_file(self, file_url):
        try:
            print('trying to upload file with url: ', file_url)
            file_response = requests.get(file_url)
            file_response.raise_for_status()
            # print('file response text ', file_response.text)

            file_stream = io.BytesIO(file_response.content)
            file_stream.seek(0)

            # Set the filename for the uploaded file
            # filename = file_url.split("/")[-1]
            filename = 'Print_me.gcode'

            # Prepare the files and data for the upload
            files = {'file': (filename, file_stream)}
            data = {'print': 'true'}

            # Perform the file upload
            print('Trying to upload to printer URL: ', self.printer_url)
            response = requests.post(self.printer_url + '/server/files/upload', files=files, data=data)
            response.raise_for_status()
            print('File transfer successful:', response.text)
        except requests.exceptions.RequestException as e:
            print('File transfer failed:', e)

if __name__ == "__main__":
    communicator = BatchPrinterConnect()