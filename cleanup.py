#!/usr/bin/env python3
"""Deletes deposit photos in captures/ older than RETENTION_DAYS.

Meant to run on a schedule via cron — NOT imported by main.py. Keeps
main.py's process simple; this runs independently even if the bin
service has been up for weeks without a restart.

Setup (run once on the Pi):
    crontab -e
  then add a line to run it daily at 3am:
    0 3 * * * /usr/bin/python3 /home/pi/trashpoint-yic/raspi/cleanup_photos.py >> /home/pi/trashpoint-yic/raspi/logs/cleanup.log 2>&1

Adjust the paths above to wherever your project actually lives.
"""

import os
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAPTURES_DIR = os.path.join(BASE_DIR, "captures")
RETENTION_DAYS = 1


def cleanup_old_photos(retention_days: int = RETENTION_DAYS) -> int:
    if not os.path.isdir(CAPTURES_DIR):
        return 0

    cutoff = time.time() - (retention_days * 86400)
    deleted = 0
    for filename in os.listdir(CAPTURES_DIR):
        if not filename.lower().endswith(".jpg"):
            continue
        filepath = os.path.join(CAPTURES_DIR, filename)
        try:
            if os.path.getmtime(filepath) < cutoff:
                os.remove(filepath)
                deleted += 1
        except OSError:
            pass  # file vanished / permission race — skip it
    return deleted


if __name__ == "__main__":
    count = cleanup_old_photos()
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] cleanup_photos: deleted {count} photo(s) older than {RETENTION_DAYS}d")