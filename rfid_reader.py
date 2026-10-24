"""EM4100 125kHz USB RFID reader (HID keyboard-emulation) via evdev.

The reader behaves like a keyboard: it "types" the card UID digits followed
by Enter. We grab the input device exclusively so taps don't leak keystrokes
into the console, then read digit keycodes until Enter.

Device selection: auto-detects the first device whose name mentions an RFID /
card reader keyword, or use the TRASHPOINT_RFID_DEVICE env var
(e.g. /dev/input/event0).
"""

import os

from evdev import InputDevice, categorize, ecodes, list_devices

KEY_DIGITS = {
    "KEY_0": "0", "KEY_1": "1", "KEY_2": "2", "KEY_3": "3", "KEY_4": "4",
    "KEY_5": "5", "KEY_6": "6", "KEY_7": "7", "KEY_8": "8", "KEY_9": "9",
}

DEVICE_KEYWORDS = ("rfid", "card", "reader", "em4100", "hid keyboard")


def _find_device() -> InputDevice:
    override = os.environ.get("TRASHPOINT_RFID_DEVICE")
    if override:
        return InputDevice(override)
    for path in list_devices():
        device = InputDevice(path)
        if any(keyword in device.name.lower() for keyword in DEVICE_KEYWORDS):
            return device
    raise RuntimeError(
        "RFID reader not found. Set TRASHPOINT_RFID_DEVICE=/dev/input/eventX"
    )


class RfidReader:
    def __init__(self):
        self.device = _find_device()
        self.device.grab()

    def wait_for_card(self) -> str:
        """Blocks until a card is tapped; returns the UID digits as a string."""
        uid = []
        for event in self.device.read_loop():
            if event.type != ecodes.EV_KEY:
                continue
            key = categorize(event)
            if key.keystate != key.key_down:
                continue
            if key.keycode == "KEY_ENTER":
                if uid:
                    return "".join(uid)
            elif key.keycode in KEY_DIGITS:
                uid.append(KEY_DIGITS[key.keycode])

    def cleanup(self):
        try:
            self.device.ungrab()
        except OSError:
            pass
        self.device.close()
