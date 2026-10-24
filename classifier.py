"""YOLOv8n-cls trash classifier (TFLite inference, no ultralytics needed on the Pi).

Loads the TFLite export of a trained YOLOv8n-cls model and classifies a
deposit photo as plastik / kaleng / lainnya.

Files expected next to this script (see README_YOLO.md):
  - model.tflite  : exported model (best_float32.tflite, renamed)
  - labels.txt    : one class name per line, ALPHABETICAL order
                    (same order ultralytics uses for training folders), e.g.:
                        kaleng
                        lainnya
                        plastik

Standalone test:
  python3 classifier.py captures/test-20260612-101500.jpg
"""

import os
import sys

import numpy as np
from PIL import Image

try:
    from tflite_runtime.interpreter import Interpreter
except ImportError:
    import tensorflow as tf
    Interpreter = tf.lite.Interpreter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = os.path.join(BASE_DIR, "model.tflite")
DEFAULT_LABELS = os.path.join(BASE_DIR, "labels.txt")


class TrashClassifier:
    def __init__(self, model_path: str = DEFAULT_MODEL, labels_path: str = DEFAULT_LABELS):
        with open(labels_path, encoding="utf-8") as f:
            self.labels = [line.strip() for line in f if line.strip()]

        self.interpreter = Interpreter(model_path=model_path)
        self.interpreter.allocate_tensors()
        self.input_detail = self.interpreter.get_input_details()[0]
        self.output_detail = self.interpreter.get_output_details()[0]

        shape = self.input_detail["shape"]
        if shape[1] == 3:  # NCHW: [1, 3, H, W]
            self.channels_first = True
            self.input_size = (shape[3], shape[2])  # width, height
        else:  # NHWC: [1, H, W, 3]
            self.channels_first = False
            self.input_size = (shape[2], shape[1])

    def classify(self, image_path: str):
        img = Image.open(image_path).convert("RGB").resize(self.input_size)
        x = np.asarray(img, dtype=np.float32) / 255.0
        if self.channels_first:
            x = np.transpose(x, (2, 0, 1))  # HWC -> CHW
        x = np.expand_dims(x, axis=0)

        self.interpreter.set_tensor(self.input_detail["index"], x)
        self.interpreter.invoke()
        probs = self.interpreter.get_tensor(self.output_detail["index"])[0]

        idx = int(np.argmax(probs))
        return self.labels[idx], float(probs[idx])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 classifier.py <path-to-photo.jpg>")
        sys.exit(1)
    label, confidence = TrashClassifier().classify(sys.argv[1])
    print(f"Result: {label} ({confidence * 100:.1f}%)")
