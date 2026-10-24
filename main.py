#!/usr/bin/env python3
"""TrashPoint smart bin — main loop.

Flow (page-based, per teammate's diagram):
  1. Page HOME (00) — idle, waiting for RFID card tap
  2. Card tapped -> page LOADING (01), look up student by rfidUid
  3. Not found -> page UNKNOWN (03), 2s delay, back to HOME
  4. Found -> page RECOGNIZED (02), show name, 2s delay
  5. Page DEPOSIT (04) — deposit session:
       - item detected on IR -> photograph, classify, sort via servo,
         tally count/points LOCALLY (not yet saved to Firebase), push
         running totals to the display, loop back to listening
       - "Selesai" button touched on the display -> end session
  6. Page SUMMARY (05) — NOW commit every tallied item to Firebase
     (one batched record_session call), 5s delay, back to HOME

Per-stage timings (capture / classify / Firebase save) are logged in
milliseconds so speed changes can be measured on the real hardware.

Env vars:
  TRASHPOINT_SERVICE_ACCOUNT  path to Firebase service-account JSON
                              (default: ./serviceAccountKey.json)
  TRASHPOINT_DATABASE_URL     Realtime Database URL (required)
  TRASHPOINT_BIN_ID           bin identifier (default: bin-001)
  TRASHPOINT_RFID_DEVICE      /dev/input/eventX override for the reader
  TRASHPOINT_MODEL            classifier model override (see cls2.py)
"""

import logging
import logging.handlers
import os
import signal
import sys
import time

from camera import DepositCamera
from cls2 import TrashClassifier
from dwin_display import (
    PAGE_DEPOSIT,
    PAGE_HOME,
    PAGE_LOADING,
    PAGE_RECOGNIZED,
    PAGE_SUMMARY,
    PAGE_UNKNOWN,
    VP_ALUMINUM_COUNT,
    VP_NAME,
    VP_PLASTIC_COUNT,
    VP_SELESAI_BUTTON,
    VP_TOTAL_POINTS,
    DwinDisplay,
)
from firebase_client import POINTS, FirebaseClient
from rfid_reader import RfidReader
from sensor import BinSensors

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# classifier labels ("plastik"/"kaleng"/"lainnya") -> item_type Firebase expects
LABEL_MAP = {
    "botol": "PLASTIC",
    "kaleng": "ALUMINUM",
    "lainnya": "OTHER",
}
MIN_CONFIDENCE = 0.6
# item_type -> servo angle for physical sorting into the right chamber
SORT_ANGLE = {
    "PLASTIC": 0,
    "ALUMINUM": 180,
}
# pause + warning beep before the servo actually moves, so hands are
# clear of the sorting mechanism — tune this up if it's still too fast
SERVO_SAFETY_DELAY_S = 0.25
# pause after the IR sensor triggers before taking the photo, so the item
# has time to settle in the chamber (not still falling / blurry)
CAPTURE_DELAY_S = 0.5
UNKNOWN_CARD_DELAY_S = 2.0
RECOGNIZED_DELAY_S = 2.0
SUMMARY_DELAY_S = 5.0
# safety net: if nobody touches Selesai and nothing new gets dropped for
# this long, auto-finish the session instead of hanging forever
SESSION_IDLE_TIMEOUT_S = 30.0
SESSION_POLL_INTERVAL_S = 0.05
# how often to ask the display which page it's showing (the Selesai
# button jumps pages internally on the DWIN side, so we detect the user
# finishing by watching for that page change rather than a touch report)
PAGE_CHECK_INTERVAL_S = 0.3


def setup_logging() -> logging.Logger:
    os.makedirs(LOGS_DIR, exist_ok=True)
    logger = logging.getLogger("trashpoint-bin")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(LOGS_DIR, "events.log"),
        maxBytes=1_000_000,
        backupCount=3,
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)
    return logger


def main() -> int:
    logger = setup_logging()

    database_url = os.environ.get("TRASHPOINT_DATABASE_URL")
    if not database_url:
        logger.error("TRASHPOINT_DATABASE_URL is not set")
        return 1
    service_account = os.environ.get(
        "TRASHPOINT_SERVICE_ACCOUNT",
        os.path.join(BASE_DIR, "serviceAccountKey.json"),
    )
    bin_id = os.environ.get("TRASHPOINT_BIN_ID", "bin-001")

    firebase = FirebaseClient(service_account, database_url, bin_id)
    reader = RfidReader()
    sensors = BinSensors()
    camera = DepositCamera()
    classifier = TrashClassifier()
    display = DwinDisplay()

    running = True

    def shutdown(signum, _frame):
        nonlocal running
        logger.info("Received signal %s, shutting down", signum)
        running = False
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("TrashPoint bin '%s' ready — waiting for cards", bin_id)

    try:
        while running:
            display.change_page(PAGE_HOME)
            try:
                rfid_uid = reader.wait_for_card()
                logger.info("Card tapped: %s", rfid_uid)
                display.change_page(PAGE_LOADING)

                uid, user = firebase.find_user_by_rfid(rfid_uid)
                if uid is None:
                    logger.warning("Unknown card: %s", rfid_uid)
                    display.change_page(PAGE_UNKNOWN)
                    sensors.flash_error()
                    time.sleep(UNKNOWN_CARD_DELAY_S)
                    continue

                name = user.get("name", "")
                logger.info("Recognized: %s (%s)", name, uid)
                display.change_page(PAGE_RECOGNIZED)
                display.write_text(VP_NAME, name)
                time.sleep(RECOGNIZED_DELAY_S)

                display.change_page(PAGE_DEPOSIT)
                session_items = []  # list of item_type strings, one per deposit
                plastic_count = 0
                aluminum_count = 0
                display.write_number(VP_PLASTIC_COUNT, 0)
                display.write_number(VP_ALUMINUM_COUNT, 0)
                display.write_number(VP_TOTAL_POINTS, 0)

                idle_deadline = time.monotonic() + SESSION_IDLE_TIMEOUT_S
                next_page_check = time.monotonic()
                while running:
                    if time.monotonic() > idle_deadline:
                        logger.info(
                            "Deposit session idle timeout — auto-finishing (%d plastic, %d aluminum)",
                            plastic_count, aluminum_count,
                        )
                        break

                    now = time.monotonic()
                    if now >= next_page_check:
                        next_page_check = now + PAGE_CHECK_INTERVAL_S
                        current_page = display.get_current_page()
                        if current_page is not None and current_page != PAGE_DEPOSIT:
                            logger.info(
                                "Display navigated to page %d (Selesai pressed) — finishing (%d plastic, %d aluminum)",
                                current_page, plastic_count, aluminum_count,
                            )
                            break

                    if not sensors.item_present():
                        sensors.light_on()
                        time.sleep(SESSION_POLL_INTERVAL_S)
                        continue

                    sensors.light_off()
                    time.sleep(CAPTURE_DELAY_S)
                    t0 = time.perf_counter()
                    frame, photo_path = camera.capture_array()
                    t1 = time.perf_counter()
                    sensors.light_off()

                    raw_label, confidence = classifier.classify_array(frame)
                    t2 = time.perf_counter()
                    logger.info(
                        "Classified: %s (%.1f%%) — capture %.0f ms, classify %.0f ms, photo %s",
                        raw_label, confidence * 100,
                        (t1 - t0) * 1000, (t2 - t1) * 1000, photo_path,
                    )
                    if confidence < MIN_CONFIDENCE:
                        logger.warning(
                            "Low-confidence classification (%.1f%% < %.0f%%), treating as OTHER",
                            confidence * 100, MIN_CONFIDENCE * 100,
                        )
                    item_type = (
                        LABEL_MAP.get(raw_label, "OTHER") if confidence >= MIN_CONFIDENCE else "OTHER"
                    )

                    if item_type == "OTHER":
                        logger.warning("Item not recognized — rejecting, waiting for next item")
                        sensors.flash_reject()
                        while sensors.item_present() and running:
                            time.sleep(SESSION_POLL_INTERVAL_S)
                        idle_deadline = time.monotonic() + SESSION_IDLE_TIMEOUT_S
                        continue

                    angle = SORT_ANGLE.get(item_type)
                    if angle is not None:
                        time.sleep(SERVO_SAFETY_DELAY_S)
                        sensors.sort_to(angle)
                        logger.info("Servo -> %d° for %s", angle, item_type)

                    session_items.append(item_type)
                    if item_type == "PLASTIC":
                        plastic_count += 1
                    elif item_type == "ALUMINUM":
                        aluminum_count += 1
                    running_points = sum(POINTS.get(t, 0) for t in session_items)

                    logger.info(
                        "Tallied (not saved yet): %s — running total %d TP",
                        item_type, running_points,
                    )
                    sensors.flash_success()

                    display.write_number(VP_PLASTIC_COUNT, plastic_count)
                    display.write_number(VP_ALUMINUM_COUNT, aluminum_count)
                    display.write_number(VP_TOTAL_POINTS, running_points)

                    while sensors.item_present() and running:
                        time.sleep(SESSION_POLL_INTERVAL_S)
                    idle_deadline = time.monotonic() + SESSION_IDLE_TIMEOUT_S

                # --- commit to Firebase, whole session in one batch -------
                display.change_page(PAGE_SUMMARY)
                t0 = time.perf_counter()
                total_points = firebase.record_session(uid, session_items)
                save_ms = (time.perf_counter() - t0) * 1000
                display.write_number(VP_PLASTIC_COUNT, plastic_count)
                display.write_number(VP_ALUMINUM_COUNT, aluminum_count)
                display.write_number(VP_TOTAL_POINTS, total_points)
                logger.info(
                    "Session saved for %s: %d plastic, %d aluminum, %d TP (Firebase %.0f ms)",
                    name, plastic_count, aluminum_count, total_points, save_ms,
                )
                time.sleep(SUMMARY_DELAY_S)
            except Exception:
                logger.exception("Session failed")
                sensors.flash_error()
    finally:
        reader.cleanup()
        camera.cleanup()
        sensors.cleanup()
        display.cleanup()
        logger.info("Shutdown complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())