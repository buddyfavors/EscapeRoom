from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from escape_room.config import PUNISHMENTS_FILE


@dataclass(frozen=True)
class PunishmentEntry:
    """One spoke on the wheel; `message` is the player-facing copy."""

    raw: str
    message: str


def default_punishments_path() -> Path:
    return PUNISHMENTS_FILE


def _classify(raw: str) -> PunishmentEntry | None:
    line = raw.strip()
    if not line or line.startswith("#"):
        return None
    if line.lower().startswith("text:"):
        body = line.split(":", 1)[1].strip()
        if not body:
            return None
        return PunishmentEntry(raw=line, message=body)
    return PunishmentEntry(raw=line, message=line)


def split_punishment_display(text: str) -> tuple[str, str]:
    """Split 'Title: body' wheel lines into a short label and detail text."""
    line = text.strip()
    if ": " in line:
        title, body = line.split(": ", 1)
        title = title.strip()
        body = body.strip()
        if title and body:
            return title, body
    return line, ""


def parse_punishments(text: str) -> list[PunishmentEntry]:
    out: list[PunishmentEntry] = []
    for line in text.splitlines():
        entry = _classify(line)
        if entry is not None:
            out.append(entry)
    return out


def serialize_punishments(entries: list[PunishmentEntry]) -> str:
    header = (
        "# KnottyBytes Escape Room — Wheel of Punishments\n"
        "# One punishment per line. '#' lines ignored.\n"
        "# Use 'Title: details' to show a short title above the details.\n"
    )
    body = "\n".join(e.raw for e in entries)
    return header + body + ("\n" if body else "")


def load_punishments(path: Path | None = None) -> list[PunishmentEntry]:
    p = path or default_punishments_path()
    if not p.exists():
        return []
    return parse_punishments(p.read_text(encoding="utf-8"))


def save_punishments_text(text: str, path: Path | None = None) -> list[PunishmentEntry]:
    p = path or default_punishments_path()
    entries = parse_punishments(text)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(serialize_punishments(entries), encoding="utf-8")
    return entries


def validate_punishments_text(text: str) -> tuple[bool, str]:
    """The format is forgiving — the only error case is an empty 'text:' entry."""
    bad: list[str] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if line.lower().startswith("text:") and not line.split(":", 1)[1].strip():
            bad.append(f"line {i}: empty 'text:' entry.")
    if bad:
        return False, "\n".join(bad)
    return True, ""
