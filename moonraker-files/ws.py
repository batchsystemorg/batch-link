import json
import logging
import websocket

import os

class Socket:
    def __init__(self, on_open, on_message, on_close, on_error, url):
        self.connect(on_open, on_message, on_close, on_error, url)

    def run(self):
        try:
            self.socket.run_forever()
        except Exception as e:
            print("Socket run: %s", e)
            pass

    def send_msg(self, msg):
        try:
            if isinstance(msg, dict):
                msg = json.dumps(msg)
            if self.connected() and self.socket is not None:
                self.socket.send(msg)
        except Exception as e:
            print("Socket send_msg: %s", e)
            pass

    def connected(self):
        return self.socket.sock and self.socket.sock.connected

    def connect(self, on_open, on_message, on_close, on_error, url):
        # url = url + "?token=" + token
        self.socket = websocket.WebSocketApp(
            url,
            on_open=on_open,
            on_message=on_message,
            on_close=on_close,
            on_error=on_error,
        )

    def disconnect(self):
        print("Disconnecting the websocket...")
        self.socket.keep_running = False
        self.socket.close()
        print("The websocket has been closed.")