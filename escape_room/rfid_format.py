from __future__ import annotations


def normalize_rfid_tag(raw: str) -> str | None:
    """
    Fobs/badges read as a 10-digit decimal string (keyboard HID + Enter).

    Only inputs that normalize to exactly ten digits are treated as RFID tags;
    shorter digit strings are reserved for lock combination attempts (3/4 digits).
    """
    d = "".join(c for c in raw.strip() if c.isdigit())
    if len(d) > 10:
        d = d[-10:]
    if len(d) != 10:
        return None
    return d
