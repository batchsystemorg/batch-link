import os
import json
from logger import setup_logging

from configparser import ConfigParser
from ws import Socket

CONFIG_FILE_PATH = os.path.expanduser('~/printer_data/config/moonraker-mattaconnect.cfg')


class MoonrakerWsPlugin():

    def __init__(self):
        self.config = ConfigParser()
        self.config.read(CONFIG_FILE_PATH)
        self.MOONRAKER_API_URL = f"http://{self.config.get('moonraker_control', 'printer_ip')}:{self.config.get('moonraker_control', 'printer_port')}"

        self.logger.info("---------- Starting MattaConnectPlugin ----------")
        self.websocket = Socket(
            logger_ws = self._logger_ws,
            on_open=lambda ws: self.ws_on_open(ws),
            on_message=lambda ws, msg: self.ws_on_message(ws, msg),
            on_close=lambda ws, close_status_code, close_msg: self.ws_on_close(
                ws, close_status_code, close_msg
            ),
            on_error=lambda ws, error: self.ws_on_error(ws, error),
            url=''
        )