"""Run the escape room web server (RFID: evdev on Pi, Raw Input on Windows)."""

from __future__ import annotations

import uvicorn

from escape_room.config import WEB_HOST, WEB_PORT

if __name__ == "__main__":
    uvicorn.run("escape_room.main:app", host=WEB_HOST, port=WEB_PORT, reload=False)
