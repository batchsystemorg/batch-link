# --------------- BATCH WORKS API <-> MOONRAKER  --------------- #
import configparser
import websocket
import threading
import time
import requests
import json
import io

# --------------------------- URLs --------------------------- #
remote_websocket_url = "wss://moonraker-api.onrender.com"
printer_websocket_url = "ws://localhost/websocket"
printer_url = "http://localhost"


# --------------------------- READ Printer Config --------------------------- #
config_file_path = '/home/pi/printer_data/config/batch-server.cfg'
config = configparser.ConfigParser()
config.read(config_file_path)
auth_key = None

if 'batch_auth' in config and 'UUID' in config['batch_auth']:
    uuid = config['batch_auth']['UUID']
    print('Printer KEY:', auth_key)
else:
    print('Printer has no key')

# --------------------------- REMOTE WEBSOCKT --------------------------- #
def remote_on_message(ws, message):
    print(f"Received from remote: {message}")
    data = json.loads(message)
    if 'action' in data and 'content' in data:
        if data['action'] == 'print':
            print('Received print command for URL: ', data['content'])
            print_file(printer_url, data['content'])
        else:
            print('Unknown Command')


def remote_on_error(ws, error):
    print(f"Error remote: {error}")

def remote_on_close(ws, close_status_code, close_msg):
    print(f"Connection remote closed with status code {close_status_code}: {close_msg}")

def remote_on_open(ws):
    auth_message = {
        "action": "auth",
        "content": uuid
    }
    ws.send(json.dumps(auth_message))
    print("Connection remote opened")

remote_ws = websocket.WebSocketApp(remote_websocket_url, on_open=remote_on_open, on_message=remote_on_message, on_error=remote_on_error, on_close=remote_on_close)
remote_thread = threading.Thread(target=remote_ws.run_forever)
remote_thread.start()


# --------------------------- PRINTER WEBSOCKT --------------------------- #
def printer_on_message(ws, message):
    # print(f"Received from printer: {message}")
    return

def printer_on_error(ws, error):
    print(f"Error from printer: {error}")

def printer_on_close(ws, close_status_code, close_msg):
    print(f"Connection closed with status code {close_status_code}: {close_msg}")

def printer_on_open(ws):
    print("Connection to printer opened")


printer_ws = websocket.WebSocketApp(printer_websocket_url, on_open=printer_on_open, on_message=printer_on_message, on_error=printer_on_error, on_close=printer_on_close)
printer_thread = threading.Thread(target=printer_ws.run_forever)
printer_thread.start()


# --------------------------- POST REQUEST FUNCTIONALITY --------------------------- #

def print_file(printer_address, file_url):
    try:
        file_response = requests.get(file_url)
        file_response.raise_for_status()

        file_stream = io.BytesIO(file_response.content)

        # Set the filename for the uploaded file
        filename = file_url.split("/")[-1]

        # Prepare the files and data for the upload
        files = {'file': (filename, file_stream)}
        data = {'print': 'true'}

        # Perform the file upload
        response = requests.post(printer_address + '/server/files/upload', files=files, data=data)
        response.raise_for_status()
        print('File transfer successful:', response.text)
    except requests.exceptions.RequestException as e:
        print('File transfer failed:', e)
