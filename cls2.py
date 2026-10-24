"""YOLOv8n-cls trash classifier (TFLite inference, no ultralytics needed on the Pi).

Loads the TFLite export of a trained YOLOv8n-cls model and classifies a
deposit photo as botol / kaleng / lainnya.

Files expected next to this script (see README_YOLO.md):
  - model.tflite  : exported model (best_float32.tflite, renamed)
  - labels.txt    : one class name per line, ALPHABETICAL order
                    (same order ultralytics uses for training folders), e.g.:
                        botol
                        kaleng
                        lainnya

Both float32 and INT8-quantized exports work: if the model's input/output
tensors are int8/uint8, values are (de)quantized with the tensor's own
scale/zero-point automatically.

Env vars:
  TRASHPOINT_MODEL        model path override (e.g. model_int8.tflite)
  TRASHPOINT_CLS_THREADS  CPU threads for inference (default 4 = all Pi 3B+ cores)

Standalone test:
  python3 cls2.py captures/test-20260612-101500.jpg
"""

import os
import sys
import time

import numpy as np
from PIL import Image

try:
    from ai_edge_litert.interpreter import Interpreter
except ImportError:
    import tensorflow as tf
    Interpreter = tf.lite.Interpreter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = os.environ.get("TRASHPOINT_MODEL", os.path.join(BASE_DIR, "model.tflite"))
DEFAULT_LABELS = os.path.join(BASE_DIR, "labels.txt")
DEFAULT_THREADS = int(os.environ.get("TRASHPOINT_CLS_THREADS", "4"))


class TrashClassifier:
    def __init__(
        self,
        model_path: str = DEFAULT_MODEL,
        labels_path: str = DEFAULT_LABELS,
        num_threads: int = DEFAULT_THREADS,
    ):
        with open(labels_path, encoding="utf-8") as f:
            self.labels = [line.strip() for line in f if line.strip()]

        self.interpreter = Interpreter(model_path=model_path, num_threads=num_threads)
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

        # the first invoke() is much slower than the rest (lazy kernel
        # setup), so pay that cost now instead of on the first student
        self.interpreter.set_tensor(
            self.input_detail["index"],
            np.zeros(shape, dtype=self.input_detail["dtype"]),
        )
        self.interpreter.invoke()

    def classify(self, image_path: str):
        """Classifies a photo file. Returns (label, confidence)."""
        return self._predict(Image.open(image_path).convert("RGB"))

    def classify_array(self, rgb: np.ndarray):
        """Classifies an HxWx3 RGB uint8 array straight from the camera,
        skipping the JPEG encode -> disk -> decode round trip."""
        return self._predict(Image.fromarray(rgb[:, :, :3]))

    def _predict(self, img: Image.Image):
        x = np.asarray(img.resize(self.input_size), dtype=np.float32) / 255.0
        if self.channels_first:
            x = np.transpose(x, (2, 0, 1))  # HWC -> CHW
        x = np.expand_dims(x, axis=0)

        in_dtype = self.input_detail["dtype"]
        if in_dtype != np.float32:  # quantized input: real -> int
            scale, zero_point = self.input_detail["quantization"]
            info = np.iinfo(in_dtype)
            x = np.clip(np.round(x / scale + zero_point), info.min, info.max).astype(in_dtype)

        self.interpreter.set_tensor(self.input_detail["index"], x)
        self.interpreter.invoke()
        probs = self.interpreter.get_tensor(self.output_detail["index"])[0]

        if self.output_detail["dtype"] != np.float32:  # quantized output: int -> real
            scale, zero_point = self.output_detail["quantization"]
            probs = (probs.astype(np.float32) - zero_point) * scale

        idx = int(np.argmax(probs))
        return self.labels[idx], float(probs[idx])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 cls2.py <photo.jpg> [more photos ...]")
        print("  compare models: TRASHPOINT_MODEL=model_int8.tflite python3 cls2.py captures/*.jpg")
        sys.exit(1)
    clf = TrashClassifier()
    timings = []
    for path in sys.argv[1:]:
        start = time.perf_counter()
        label, confidence = clf.classify(path)
        timings.append((time.perf_counter() - start) * 1000)
        print(f"{os.path.basename(path)}: {label} ({confidence * 100:.1f}%) in {timings[-1]:.0f} ms")
    if len(timings) > 1:
        print(f"average: {sum(timings) / len(timings):.0f} ms/photo over {len(timings)} photos")
