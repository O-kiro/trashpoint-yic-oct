from flask import Flask, render_template, jsonify, request
from picamera2 import Picamera2
from time import sleep
import os
import threading

app = Flask(__name__)

picam2 = Picamera2()
picam2.configure(picam2.create_still_configuration())
picam2.start()
sleep(2)

# folder tempat nyimpen foto, biar rapi per kelas (plastik/kaleng/lainnya)
SAVE_DIR = "dataset"
os.makedirs(SAVE_DIR, exist_ok=True)

# status global buat di-poll sama frontend
state = {
    "running": False,
    "current": 0,
    "total": 0,
    "label": "",
    "last_file": ""
}


def get_next_filename(folder, prefix="foto", ext="jpg"):
    i = 1
    while True:
        filename = f"{prefix}_{i:03d}.{ext}"
        full_path = os.path.join(folder, filename)
        if not os.path.exists(full_path):
            return full_path
        i += 1


def capture_loop(label, jumlah):
    folder = os.path.join(SAVE_DIR, label)
    os.makedirs(folder, exist_ok=True)

    state["running"] = True
    state["current"] = 0
    state["total"] = jumlah
    state["label"] = label

    for i in range(jumlah):
        filename = get_next_filename(folder)
        picam2.capture_file(filename)
        state["current"] = i + 1
        state["last_file"] = filename
        print(f"tersimpan: {filename}")
        sleep(0.5)

    state["running"] = False


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/collect', methods=['POST'])
def collect():
    if state["running"]:
        return jsonify({"status": "error", "message": "masih ada proses capture yang jalan"}), 400

    data = request.get_json()
    label = data.get("label", "lainnya")
    jumlah = int(data.get("jumlah", 25))

    thread = threading.Thread(target=capture_loop, args=(label, jumlah))
    thread.start()

    return jsonify({"status": "started", "label": label, "jumlah": jumlah})


@app.route('/status')
def status():
    return jsonify(state)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)