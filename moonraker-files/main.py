import os
import time
import json

from configparser import ConfigParser
from ws import Socket

CONFIG_FILE_PATH = os.path.expanduser('~/printer_data/config/moonraker-mattaconnect.cfg')


class MoonrakerWsPlugin():
    def __init__(self):
        self.config = ConfigParser()
        self.config.read(CONFIG_FILE_PATH)
        # self.MOONRAKER_API_URL = f"http://{self.config.get('moonraker_control', 'printer_ip')}:{self.config.get('moonraker_control', 'printer_port')}"

        print("---------- Starting MattaConnectPlugin ----------")
        self.websocket = Socket(
            on_open=lambda ws: self.ws_on_open(ws),
            on_message=lambda ws, msg: self.ws_on_message(ws, msg),
            on_close=lambda ws, close_status_code, close_msg: self.ws_on_close(
                ws, close_status_code, close_msg
            ),
            on_error=lambda ws, error: self.ws_on_error(ws, error),
            url='ws://localhost:3000'
        )
    def run(self):
        # Start the WebSocket connection
        self.websocket.run()

        # Add any additional initialization or tasks here
        print("MoonrakerWsPlugin is running...")

        try:
            while True:
                # Add any periodic tasks or processing here
                moonraker_plugin.send_msg(self, "hi there")
                time.sleep(1)  # Example: Sleep for 1 second
        except KeyboardInterrupt:
            self.logger.info("MoonrakerWsPlugin terminated by user.")

if __name__ == "__main__":
    # Create an instance of the MoonrakerWsPlugin class
    moonraker_plugin = MoonrakerWsPlugin()

    # Run the MoonrakerWsPlugin
    moonraker_plugin.run()
