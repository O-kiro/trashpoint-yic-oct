"""DWIN HMI (DMG80480C043_01W) serial driver.

Talks to the display over UART using DWIN's standard frame protocol:
  Write VP:    5A A5 LEN 82 VP_HI VP_LO DATA...
  Change page: 5A A5 07 82 00 84 5A 01 PAGE_HI PAGE_LO
  Read VP:     5A A5 04 83 VP_HI VP_LO WORDS   (request)
               5A A5 LEN 83 VP_HI VP_LO WORDS DATA...  (response)
  Touch frame the screen sends back when a button VP is configured to
  report on touch: same shape as a read response, arrives unsolicited.

VP (variable pointer) addresses and PAGE_* numbers below are
PLACEHOLDERS — replace them with whatever you assign in your DGUS
Displayer project. Nothing here works until those match your project.

Wiring: Pi GPIO14 (TXD) -> DWIN RXD, GPIO15 (RXD) -> DWIN TXD, GND -> GND.
Requires /dev/serial0 enabled (raspi-config -> Interface Options -> Serial)
and, on a Pi 3B+, dtoverlay=disable-bt in /boot/firmware/config.txt so the
UART isn't shared with Bluetooth.

Install: pip3 install pyserial --break-system-packages
"""

import time

import serial

# --- VP map: EDIT THESE to match your DGUS Displayer project -------------
VP_PLASTIC_COUNT = 0x1000    # number display, 1 word
VP_ALUMINUM_COUNT = 0x1001   # number display, 1 word
VP_TOTAL_POINTS = 0x1002     # number display, 1 word
VP_SELESAI_BUTTON = 0x2000   # touch control (Return Key Code / Variable Icon)
VP_NAME = 0x3000             # text display, student name
# ---------------------------------------------------------------------------

# DWIN system VP that always holds the currently-displayed page number.
# Used as a fallback way to detect navigation when a button is configured
# to jump pages internally instead of reporting a touch over serial.
CURRENT_PAGE_VP = 0x0014

# --- Page numbers: EDIT THESE to match your DGUS Displayer project -------
PAGE_HOME = 0        # idle, waiting for card
PAGE_LOADING = 1      # card tapped, checking against database
PAGE_RECOGNIZED = 2   # valid card, shows name
PAGE_UNKNOWN = 3       # invalid/unrecognized card
PAGE_DEPOSIT = 4       # Setor Botol/Kaleng — deposit mode
PAGE_SUMMARY = 5       # Selesai & Ringkasan Poin — UPDATE this after you
                        # finish deleting/renumbering pages in DGUS
# ---------------------------------------------------------------------------

SERIAL_PORT = "/dev/serial0"
BAUD_RATE = 115200

FRAME_HEADER = bytes([0x5A, 0xA5])
PAGE_CHANGE_PASSWORD = bytes([0x5A, 0x01])


class DwinDisplay:
    def __init__(self, port: str = SERIAL_PORT, baud: int = BAUD_RATE):
        self.ser = serial.Serial(port, baud, timeout=0.1)

    def write_number(self, vp: int, value: int, words: int = 1):
        """Writes an unsigned integer into `words` 16-bit words at `vp`."""
        value = max(0, int(value))
        data = value.to_bytes(words * 2, byteorder="big")
        self._write_vp(vp, data)

    def write_text(self, vp: int, text: str, max_bytes: int = 32):
        """Writes an ASCII string into a text-display VP, always writing
        exactly max_bytes (padded with 0x00) so a shorter new name fully
        overwrites a longer previous one instead of leaving stale
        trailing characters on screen."""
        encoded = text.encode("ascii", errors="replace")[:max_bytes]
        encoded = encoded.ljust(max_bytes, b"\x00")
        self._write_vp(vp, encoded)

    def change_page(self, page_number: int):
        """Switches the DWIN display to `page_number`."""
        page_bytes = page_number.to_bytes(2, byteorder="big")
        body = bytes([0x82, 0x00, 0x84]) + PAGE_CHANGE_PASSWORD + page_bytes
        length = len(body)
        frame = FRAME_HEADER + bytes([length]) + body
        self.ser.write(frame)
        time.sleep(0.05)

    def read_vp(self, vp: int, words: int = 1, timeout_s: float = 0.3):
        """Requests `words` 16-bit words starting at `vp` and returns the
        value as an int (only the first word if words>1), or None if no
        valid response arrived within timeout_s.

        Clears any stale bytes sitting in the input buffer first so an
        old unrelated frame doesn't get mistaken for this response.
        """
        self.ser.reset_input_buffer()
        request = FRAME_HEADER + bytes([0x04, 0x83]) + vp.to_bytes(2, "big") + bytes([words])
        self.ser.write(request)

        total_bytes = 7 + words * 2  # header(2)+len(1)+cmd(1)+vp(2)+wordcount(1)+data
        deadline = time.monotonic() + timeout_s
        buf = b""
        while time.monotonic() < deadline and len(buf) < total_bytes:
            if self.ser.in_waiting:
                buf += self.ser.read(self.ser.in_waiting)
            else:
                time.sleep(0.01)

        if len(buf) < total_bytes:
            return None
        frame = list(buf[:total_bytes])
        if frame[0] != 0x5A or frame[1] != 0xA5 or frame[3] != 0x83:
            return None
        value = (frame[7] << 8) | frame[8]
        return value

    def get_current_page(self):
        """Asks the display which page it's currently showing.
        Returns the page number, or None if the read failed."""
        return self.read_vp(CURRENT_PAGE_VP, words=1)

    def _write_vp(self, vp: int, data: bytes):
        vp_bytes = vp.to_bytes(2, byteorder="big")
        body = bytes([0x82]) + vp_bytes + data
        length = len(body)
        frame = FRAME_HEADER + bytes([length]) + body
        self.ser.write(frame)
        time.sleep(0.05)

    def poll_touch(self):
        """Non-blocking check for an incoming touch frame (fixed 9 bytes) —
        only fires if the touched control is configured to report over
        serial. Kept for controls that DO report (leave unused if your
        Selesai button only does an internal page jump; use
        get_current_page() polling instead in that case).

        Returns (vp_address, value) if a full frame was received, else None.
        """
        if self.ser.in_waiting < 9:
            return None
        raw = self.ser.read(9)
        frame = list(raw)
        if frame[0] != 0x5A or frame[1] != 0xA5 or frame[3] != 0x83:
            return None
        vp = (frame[4] << 8) | frame[5]
        value = (frame[7] << 8) | frame[8]
        return vp, value

    def wait_for_button(self, vp: int, timeout_s: float = 30.0) -> bool:
        """Blocks until the given button VP is touched, or timeout.
        Returns True if pressed, False on timeout."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            result = self.poll_touch()
            if result and result[0] == vp:
                return True
            time.sleep(0.05)
        return False

    def cleanup(self):
        self.ser.close()


if __name__ == "__main__":
    # quick manual test: switches page, writes values, then polls the
    # current-page VP to see when you navigate to PAGE_SUMMARY yourself
    d = DwinDisplay()
    print("Switching to deposit page...")
    d.change_page(PAGE_DEPOSIT)
    time.sleep(0.5)
    d.write_number(VP_PLASTIC_COUNT, 3)
    d.write_number(VP_ALUMINUM_COUNT, 2)
    d.write_number(VP_TOTAL_POINTS, 50)
    d.write_text(VP_NAME, "Test User")
    print("Values sent. Now tap Selesai on the screen — watching current page (20s)...")
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        page = d.get_current_page()
        if page is not None:
            print("Current page:", page)
            if page == PAGE_SUMMARY:
                print("-> reached summary page!")
                break
        time.sleep(0.5)
    d.cleanup()