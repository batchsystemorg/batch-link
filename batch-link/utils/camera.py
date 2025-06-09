import logging
import os
import requests
import asyncio
from datetime import datetime

# ************* CAMERA *************** #
def fetch_snapshot(self):
    try:
        response = requests.get(
            f"{self.printer_url}:8080/?action=snapshot",
            headers=self.headers,
            stream=True
        )
        response.raise_for_status()
        return response.content  # Returns the image as bytes
    except Exception as e:
        logging.error(f"Failed to fetch snapshot: {e}")
        return None
    
async def capture_images(self):
    while True:
        if self.updates['status'] == 'printing' and self.last_status != 'printing':
            self.start_new_recording()
        elif self.updates['status'] != 'printing' and self.last_status == 'printing':
            self.current_recording_folder = None

        if self.current_recording_folder:
            # ret, frame = self.camera.read()
            # logging.info(f"Ret: {ret} and frame: {frame} from camera read")
            # if ret:
            #     timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            #     gcode_command = self.get_current_gcode_command()
            #     if gcode_command:
            #         filename = f"{gcode_command}_{timestamp}.jpg"
            #     else:
            #         filename = f"{timestamp}.jpg"
            #     image_path = os.path.join(self.current_recording_folder, filename)
            #     cv2.imwrite(image_path, frame)
            #     logging.info(f"Saved image: {image_path}")
            snapshot = self.fetch_snapshot()
            if snapshot:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                gcode_command = self.get_current_gcode_command()
                if gcode_command:
                    filename = f"{gcode_command}_{timestamp}.jpg"
                else:
                    filename = f"{timestamp}.jpg"
                image_path = os.path.join(self.current_recording_folder, filename)
                with open(image_path, "wb") as image_file:
                    image_file.write(snapshot)
                logging.info(f"Saved image: {image_path}")

        self.last_status = self.updates['status']
        await asyncio.sleep(2)  # Capture images every second

def start_new_recording(self):
    # Create a new folder for the recording
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    self.current_recording_folder = os.path.expanduser(f"~/printer-image-data/{timestamp}")
    os.makedirs(self.current_recording_folder, exist_ok=True)
    logging.info(f"Started new recording in folder: {self.current_recording_folder}")