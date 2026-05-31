"""Log Raw Input from the RFID reader for 30 seconds (set RFID_DEBUG=1)."""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["RFID_DEBUG"] = "1"
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from escape_room.config import RFID_DEVICE_PATH  # noqa: E402
from escape_room.rfid import create_rfid_listener  # noqa: E402
from escape_room.rfid_windows import list_keyboard_devices, resolve_target_device  # noqa: E402


def main() -> None:
    print("RFID_DEVICE_PATH:", RFID_DEVICE_PATH)
    for handle, name in list_keyboard_devices():
        print(f"  {int(handle):#x}  {name}")
    handle, name, null_ok = resolve_target_device(RFID_DEVICE_PATH)
    print("Target:", name or "(none)", "| null hDevice fallback:", null_ok, "\n")

    scans: list[str] = []
    listener = create_rfid_listener(RFID_DEVICE_PATH, scans.append)
    if not listener.start():
        print("Listener failed to start.")
        raise SystemExit(1)

    print("Listening 30s — scan a tag on the USB reader now…")
    time.sleep(30)
    listener.stop()
    print("Scans:", scans or "(none — no Enter-terminated buffer from matched device)")


if __name__ == "__main__":
    main()
