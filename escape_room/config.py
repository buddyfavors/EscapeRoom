from __future__ import annotations

import os
from pathlib import Path

from escape_room.rfid_common import DEFAULT_LINUX_DEVICE_PATH

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
CODES_FILE = DATA_DIR / "codes.json"
RFID_TAGS_FILE = DATA_DIR / "rfid_tags.txt"
PUNISHMENTS_FILE = DATA_DIR / "punishments.txt"
ROOM_SETTINGS_FILE = DATA_DIR / "room_settings.json"

# Linux/Pi: evdev path under /dev/input/by-id/…
# Windows: HID path substring or VID_xxxx&PID_yyyy (auto-matches RFID_Reader from default).
RFID_DEVICE_PATH = os.environ.get("RFID_DEVICE", DEFAULT_LINUX_DEVICE_PATH)

WEB_HOST = os.environ.get("ESCAPE_ROOM_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("ESCAPE_ROOM_PORT", "8000"))

# Arcade / LED minigames (reaction rush, Simon, etc.). Set MINIGAMES_ENABLED=1 to turn back on.
MINIGAMES_ENABLED = os.environ.get("MINIGAMES_ENABLED", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
