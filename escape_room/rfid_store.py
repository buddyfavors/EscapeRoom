from __future__ import annotations

from pathlib import Path

from escape_room.config import RFID_TAGS_FILE
from escape_room.models import RfidTagFile


def default_rfid_path() -> Path:
    return RFID_TAGS_FILE


def _parse_text(text: str) -> list[str]:
    """
    Lenient parse: one 10-digit tag per line. Blank lines and '#' comments are ignored.
    Non-digit characters are stripped from each line; lines that don't yield exactly
    10 digits are dropped. Duplicates are removed while preserving order.
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        digits = "".join(c for c in line if c.isdigit())
        if len(digits) > 10:
            digits = digits[-10:]
        if len(digits) != 10:
            continue
        if digits in seen:
            continue
        seen.add(digits)
        out.append(digits)
    return out


def _serialize(tags: list[str]) -> str:
    header = (
        "# KnottyBytes Escape Room — RFID tag list\n"
        "# One 10-digit tag per line. Lines starting with '#' are ignored.\n"
        "# On scan, the game rolls a random good/bad outcome per tag.\n"
    )
    body = "\n".join(tags)
    return header + body + ("\n" if body else "")


def load_rfid_tags(path: Path | None = None) -> RfidTagFile:
    p = path or default_rfid_path()
    if not p.exists():
        return RfidTagFile()
    text = p.read_text(encoding="utf-8")
    return RfidTagFile(tags=_parse_text(text))


def save_rfid_tags_text(text: str, path: Path | None = None) -> RfidTagFile:
    p = path or default_rfid_path()
    tags = _parse_text(text)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_serialize(tags), encoding="utf-8")
    return RfidTagFile(tags=tags)


def validate_rfid_tags_text(text: str) -> tuple[bool, str]:
    """
    The text format is intentionally forgiving — any line that isn't a comment/blank
    must yield exactly 10 digits after stripping non-digits. Report bad lines.
    """
    bad: list[str] = []
    for i, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        digits = "".join(c for c in line if c.isdigit())
        if len(digits) > 10:
            digits = digits[-10:]
        if len(digits) != 10:
            bad.append(f"line {i}: '{raw_line}' (needs 10 digits)")
    if bad:
        return False, "Bad tag lines:\n" + "\n".join(bad)
    return True, ""
