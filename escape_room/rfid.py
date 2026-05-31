from __future__ import annotations

import sys

from escape_room.rfid_common import DEFAULT_LINUX_DEVICE_PATH, DigitHandler, RfidListener


def create_rfid_listener(device_spec: str, on_submit_buffer: DigitHandler) -> RfidListener:
    """
    Create a platform-appropriate RFID keyboard listener.

    - Linux / Raspberry Pi: evdev on RFID_DEVICE path
    - Windows: Raw Input on the matching HID keyboard device
    """
    if sys.platform == "win32":
        from escape_room.rfid_windows import WindowsRfidListener

        return WindowsRfidListener(device_spec, on_submit_buffer)

    from escape_room.rfid_evdev import EvdevRfidListener

    return EvdevRfidListener(device_spec, on_submit_buffer)


# Backward-compatible alias used by main.py imports.
RfidKeyboardListener = create_rfid_listener

__all__ = [
    "DEFAULT_LINUX_DEVICE_PATH",
    "DigitHandler",
    "RfidKeyboardListener",
    "RfidListener",
    "create_rfid_listener",
]
