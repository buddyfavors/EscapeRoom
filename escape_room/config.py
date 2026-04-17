from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
CODES_FILE = DATA_DIR / "codes.json"
RFID_TAGS_FILE = DATA_DIR / "rfid_tags.txt"

# Default matches the original POC device path (override on Pi or other installs).
RFID_DEVICE_PATH = os.environ.get(
    "RFID_DEVICE",
    "/dev/input/by-id/usb-X_RFID_Reader_20220908-event-kbd",
)

WEB_HOST = os.environ.get("ESCAPE_ROOM_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("ESCAPE_ROOM_PORT", "8000"))
