import websocket
import time

def on_message(ws, message):
    print(f"Received: {message}")

def on_error(ws, error):
    print(f"Error: {error}")

def on_close(ws, close_status_code, close_msg):
    print(f"Connection closed with status code {close_status_code}: {close_msg}")

def on_open(ws):
    print("Connection opened")

# websocket_url = "ws://192.168.110.80:3777"  # Replace with your Render.com URL
websocket_url = "wss://moonraker-api.onrender.com"  # Replace with your Render.com URL

ws = websocket.WebSocketApp(websocket_url, on_message=on_message, on_error=on_error, on_close=on_close)
ws.on_open = on_open

ws.run_forever()
