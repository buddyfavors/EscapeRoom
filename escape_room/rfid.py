from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

try:
    from evdev import InputDevice, ecodes
except ImportError:  # pragma: no cover - Windows / non-Linux dev
    InputDevice = None  # type: ignore[misc, assignment]
    ecodes = None  # type: ignore[misc, assignment]


DigitHandler = Callable[[str], None]


def _digit_from_event_code(code: int) -> str | None:
    if ecodes is None:
        return None
    mapping = {
        ecodes.KEY_0: "0",
        ecodes.KEY_1: "1",
        ecodes.KEY_2: "2",
        ecodes.KEY_3: "3",
        ecodes.KEY_4: "4",
        ecodes.KEY_5: "5",
        ecodes.KEY_6: "6",
        ecodes.KEY_7: "7",
        ecodes.KEY_8: "8",
        ecodes.KEY_9: "9",
    }
    return mapping.get(code)


class RfidKeyboardListener:
    """
    Listens for keyboard-style RFID reader events (digits + Enter).
    Runs in a background thread; calls on_submit_buffer when Enter is pressed.
    """

    def __init__(self, device_path: str, on_submit_buffer: DigitHandler) -> None:
        self._device_path = device_path
        self._on_submit = on_submit_buffer
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> bool:
        if InputDevice is None:
            logger.warning("evdev not installed; RFID listener disabled.")
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="rfid-listener", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        try:
            dev = InputDevice(self._device_path)
        except OSError as e:
            logger.warning("RFID device not available (%s): %s", self._device_path, e)
            return

        buffer = ""
        try:
            for event in dev.read_loop():
                if self._stop.is_set():
                    break
                if event.type != ecodes.EV_KEY or event.value != 1:
                    continue
                digit = _digit_from_event_code(event.code)
                if digit is not None:
                    buffer += digit
                    continue
                if event.code == ecodes.KEY_ENTER:
                    submitted = buffer
                    buffer = ""
                    if submitted:
                        self._on_submit(submitted)
        finally:
            try:
                dev.close()
            except OSError:
                pass
