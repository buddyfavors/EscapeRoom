"""
Legacy entrypoint — the RFID POC now lives in the `escape_room` package.

Run the full experience (web UI + game + optional RFID):

  python run.py

On Raspberry Pi, install Linux dependencies:

  pip install -r requirements-rpi.txt

Optional environment variables:
  RFID_DEVICE   path to evdev input device (default matches the original POC reader)
  ESCAPE_ROOM_HOST / ESCAPE_ROOM_PORT   bind address (default 0.0.0.0:8000)
"""

from __future__ import annotations

import uvicorn

from escape_room.config import WEB_HOST, WEB_PORT

if __name__ == "__main__":
    uvicorn.run("escape_room.main:app", host=WEB_HOST, port=WEB_PORT, reload=False)
