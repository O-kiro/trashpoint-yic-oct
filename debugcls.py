#!/usr/bin/env python3
"""Debug tool — runs the classifier on a photo and prints the RAW
probability for every class, not just the winning one.

This tells you whether:
  - the model is genuinely confused (probabilities spread out / close)
  - labels.txt is likely mismatched with training order (a class you know
    is right gets a high score, but under the WRONG label)
  - one class dominates almost everything (bad/imbalanced training data)

Usage:
    python3 debug_classify.py captures/some-can-photo.jpg
    python3 debug_classify.py captures/*.jpg      # check several at once
"""

import sys

# use whichever classifier module you're actually running — cls2 per
# your Pi setup
from classifier import DEFAULT_LABELS, TrashClassifier


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 debug_classify.py <photo1.jpg> [photo2.jpg ...]")
        sys.exit(1)

    with open(DEFAULT_LABELS, encoding="utf-8") as f:
        labels = [line.strip() for line in f if line.strip()]
    print(f"labels.txt order: {labels}\n")

    clf = TrashClassifier()

    for path in sys.argv[1:]:
        img = __import__("PIL.Image", fromlist=["Image"]).open(path).convert("RGB")
        img = img.resize(clf.input_size)
        import numpy as np
        x = np.asarray(img, dtype=np.float32) / 255.0
        if clf.channels_first:
            x = np.transpose(x, (2, 0, 1))
        x = np.expand_dims(x, axis=0)

        clf.interpreter.set_tensor(clf.input_detail["index"], x)
        clf.interpreter.invoke()
        probs = clf.interpreter.get_tensor(clf.output_detail["index"])[0]

        print(f"--- {path} ---")
        for label, prob in zip(clf.labels, probs):
            marker = " <-- picked" if prob == max(probs) else ""
            print(f"  {label:10s}: {prob*100:5.1f}%{marker}")
        print()


if __name__ == "__main__":
    main()