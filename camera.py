"""OV5647 (Pi Camera v1) deposit-photo capture via picamera2.

Each deposit is photographed and saved to captures/{timestamp}.jpg for
verification/log. Local only — cloud upload is out of scope (PRD §11).
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image
from picamera2 import Picamera2

CAPTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")
JPEG_QUALITY = 90


class DepositCamera:
    def __init__(self):
        os.makedirs(CAPTURES_DIR, exist_ok=True)
        self.camera = Picamera2()
        # picamera2's "BGR888" is stored as R,G,B per pixel in the numpy
        # array, i.e. capture_array() gives a ready-to-use RGB image
        config = self.camera.create_still_configuration(
            main={"size": (1296, 972), "format": "BGR888"}
        )
        self.camera.configure(config)
        self.camera.start()
        time.sleep(1.0)  # let auto-exposure settle
        # one background worker writes JPEGs so the deposit loop never
        # waits on encoding + SD-card writes
        self._saver = ThreadPoolExecutor(max_workers=1, thread_name_prefix="photo-save")

    def capture(self) -> str:
        """Captures a JPEG; returns the saved file path."""
        path = self._next_path()
        self.camera.capture_file(path)
        return path

    def capture_array(self):
        """Grabs a frame as an RGB numpy array and saves the JPEG copy in
        the background. Returns (rgb_array, photo_path) — the file may
        still be being written when this returns."""
        rgb = self.camera.capture_array("main")
        path = self._next_path()
        self._saver.submit(self._save, rgb, path)
        return rgb, path

    @staticmethod
    def _save(rgb: np.ndarray, path: str):
        Image.fromarray(rgb[:, :, :3]).save(path, quality=JPEG_QUALITY)

    @staticmethod
    def _next_path() -> str:
        # millisecond suffix so two deposits in the same second don't
        # overwrite each other now that the loop is faster
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        millis = int(time.time() * 1000) % 1000
        return os.path.join(CAPTURES_DIR, f"{timestamp}-{millis:03d}.jpg")

    def cleanup(self):
        self._saver.shutdown(wait=True)  # finish any photo still being written
        self.camera.stop()
        self.camera.close()
