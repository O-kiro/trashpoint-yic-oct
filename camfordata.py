from picamera2 import Picamera2
from time import sleep

picam2 = Picamera2()
picam2.configure(picam2.create_still_configuration())
picam2.start()
sleep(2)

for i in range(25):
    filename = f"foto_{i+1:02d}.jpg"
    picam2.capture_file(filename)
    print(f"tersimpan: {filename}")
    sleep(0.5)

picam2.stop()
print("done, 25 foto")