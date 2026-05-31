from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

DigitHandler = Callable[[str], None]

# Ignore the same buffer twice in a row within this window (reader double-fires Enter).
SUBMIT_DEDUPE_S = 0.85

DEFAULT_LINUX_DEVICE_PATH = "/dev/input/by-id/usb-X_RFID_Reader_20220908-event-kbd"


class RfidListener(Protocol):
    backend_name: str

    def start(self) -> bool: ...

    def stop(self) -> None: ...


class ScanBuffer:
    """Accumulates digit keypresses until Enter, with duplicate-submit suppression."""

    def __init__(self, on_submit: DigitHandler) -> None:
        self._on_submit = on_submit
        self._buffer = ""
        self._last_submit: str | None = None
        self._last_submit_mono: float = 0.0

    def feed_digit(self, digit: str) -> None:
        if len(digit) == 1 and digit.isdigit():
            self._buffer += digit

    def feed_enter(self) -> None:
        submitted = self._buffer
        self._buffer = ""
        if not submitted:
            return
        now = time.monotonic()
        if (
            submitted == self._last_submit
            and (now - self._last_submit_mono) < SUBMIT_DEDUPE_S
        ):
            logger.debug("RFID duplicate submit suppressed: %s…", submitted[:4])
            return
        self._last_submit = submitted
        self._last_submit_mono = now
        self._on_submit(submitted)


def linux_by_id_token(device_path: str) -> str | None:
    """Extract a stable product token from a Linux /dev/input/by-id symlink name."""
    name = Path(device_path).name
    for suffix in ("-event-kbd", "-event-mouse", "-event-joystick"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    if name.startswith("usb-"):
        name = name[4:]
    return name or None


def device_name_matcher(spec: str) -> Callable[[str], bool]:
    """
    Build a predicate that matches a platform device identifier string.

    Supports:
    - Linux evdev paths (/dev/input/by-id/…)
    - Windows HID paths (\\?\HID#VID_xxxx&PID_yyyy#…)
    - Explicit VID/PID tokens (VID_0483&PID_5750)
    - Plain substring matches
    """
    spec = spec.strip()
    if not spec:
        return lambda _name: False

    vid_pid = re.search(
        r"VID[_\s:-]?([0-9A-Fa-f]{4}).*PID[_\s:-]?([0-9A-Fa-f]{4})",
        spec,
        re.IGNORECASE,
    )
    if vid_pid:
        vid = vid_pid.group(1).upper()
        pid = vid_pid.group(2).upper()
        needle = f"VID_{vid}&PID_{pid}".upper()
        return lambda name: needle in name.upper()

    if spec.startswith("/dev/") or "by-id" in spec:
        token = linux_by_id_token(spec)
        if token:
            upper = token.upper()
            return lambda name: upper in name.upper()

    upper = spec.upper()
    return lambda name: upper in name.upper()


def preferred_match_tokens(spec: str) -> list[str]:
    """Ordered tokens to try when auto-selecting a reader on Windows."""
    tokens: list[str] = []
    if spec.startswith("/dev/") or "by-id" in spec:
        token = linux_by_id_token(spec)
        if token:
            tokens.append(token)
        for fallback in ("RFID_Reader", "RFID"):
            if fallback not in tokens:
                tokens.append(fallback)
    elif spec:
        tokens.append(spec)
    else:
        tokens.extend(["RFID_Reader", "RFID"])
    return tokens
