from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from escape_room.config import PUNISHMENTS_FILE


@dataclass(frozen=True)
class PunishmentEntry:
    """
    One spoke on the wheel. `kind` is either 'minigame' or 'text'.
    For minigame kinds, `target` is either 'random' or a specific slug
    (e.g. 'rps'). For text kinds, `message` is the player-facing copy.
    """

    raw: str
    kind: str  # "minigame" | "text"
    target: str  # slug (for minigame) or full text (for text)
    message: str


def default_punishments_path() -> Path:
    return PUNISHMENTS_FILE


def _classify(raw: str) -> PunishmentEntry | None:
    line = raw.strip()
    if not line or line.startswith("#"):
        return None
    lowered = line.lower()
    if lowered == "minigame":
        return PunishmentEntry(raw=line, kind="minigame", target="random", message="A minigame.")
    if lowered.startswith("minigame:"):
        slug = line.split(":", 1)[1].strip().lower()
        if not slug:
            slug = "random"
        return PunishmentEntry(
            raw=line, kind="minigame", target=slug, message=f"A minigame ({slug})."
        )
    if lowered.startswith("text:"):
        body = line.split(":", 1)[1].strip()
        if not body:
            return None
        return PunishmentEntry(raw=line, kind="text", target=body, message=body)
    return PunishmentEntry(raw=line, kind="text", target=line, message=line)


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
        "# Prefixes: 'minigame', 'minigame:<slug>', 'text:<msg>'.\n"
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
    """
    The format is forgiving — the only error case is a malformed explicit
    'minigame:<slug>' pointing at a slug we do not recognise.
    """
    allowed_slugs = {"random", "reaction-rush", "whack-mole", "rps", "simon", "pattern"}
    bad: list[str] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lowered = line.lower()
        if lowered.startswith("minigame:"):
            slug = line.split(":", 1)[1].strip().lower()
            if slug and slug not in allowed_slugs:
                bad.append(
                    f"line {i}: unknown minigame slug '{slug}'. "
                    f"Use one of: {', '.join(sorted(allowed_slugs))}."
                )
        elif lowered.startswith("text:"):
            body = line.split(":", 1)[1].strip()
            if not body:
                bad.append(f"line {i}: empty 'text:' entry.")
    if bad:
        return False, "\n".join(bad)
    return True, ""
