from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from escape_room.config import RFID_TAGS_FILE
from escape_room.models import RfidTagFile


def default_rfid_path() -> Path:
    return RFID_TAGS_FILE


def load_rfid_tags(path: Path | None = None) -> RfidTagFile:
    p = path or default_rfid_path()
    if not p.exists():
        return RfidTagFile()
    raw = json.loads(p.read_text(encoding="utf-8"))
    return RfidTagFile.model_validate(raw)


def save_rfid_tags_json(text: str, path: Path | None = None) -> RfidTagFile:
    p = path or default_rfid_path()
    data = json.loads(text)
    tags = RfidTagFile.model_validate(data)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(tags.model_dump(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return tags


def validate_rfid_tags_json(text: str) -> tuple[bool, str]:
    try:
        RfidTagFile.model_validate_json(text)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"
    except ValidationError as e:
        return False, str(e)
    return True, ""
