from picamera2 import Picamera2
from time import sleep
import os

picam2 = Picamera2()
picam2.configure(picam2.create_still_configuration())
picam2.start()
sleep(2)

def get_next_filename(prefix="foto", ext="jpg"):
    i = 1
    while True:
        filename = f"{prefix}_{i:03d}.{ext}"
        if not os.path.exists(filename):
            return filename, i
        i += 1

filename, start_index = get_next_filename()

for i in range(25):
    filename, _ = get_next_filename()
    picam2.capture_file(filename)
    print(f"tersimpan: {filename}")
    sleep(0.5)

picam2.stop()
print("done, 25 foto udah kelar")