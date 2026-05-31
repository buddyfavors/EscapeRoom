from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from escape_room.config import ROOM_SETTINGS_FILE
from escape_room.rfid_format import normalize_rfid_tag

DEFAULT_GM_NAME = "Gamemaster"

DEFAULT_BAD_SCAN_PHRASES: tuple[str, ...] = (
    "Bad scan — {gm} laughs.",
    "Punishment! {gm} gains an edge.",
    "{gm} savors that failure — no clue for you.",
    "Cursed tag. The house remembers.",
    "{gm} claims that one with a grin.",
    "Wrong soul, right trap — try again when you stop shaking.",
    "{gm} whispers: not today.",
    "That badge bled out — nothing earned.",
)


class RoomSettings(BaseModel):
    gamemaster_name: str = Field(default=DEFAULT_GM_NAME, min_length=1, max_length=40)
    bad_scan_phrases: list[str] = Field(default_factory=lambda: list(DEFAULT_BAD_SCAN_PHRASES))
    wildcard_free_good_tag: str | None = Field(
        default=None,
        description="10-digit RFID badge — guaranteed good scan once per game.",
    )
    wildcard_trump_tag: str | None = Field(
        default=None,
        description="10-digit RFID badge — skip the next punishment once per game.",
    )

    @field_validator("gamemaster_name", mode="before")
    @classmethod
    def _strip_name(cls, v):  # noqa: ANN001
        if v is None:
            return DEFAULT_GM_NAME
        s = str(v).strip()
        return s or DEFAULT_GM_NAME

    @field_validator("bad_scan_phrases", mode="before")
    @classmethod
    def _normalize_phrases(cls, v):  # noqa: ANN001
        if not isinstance(v, list):
            return list(DEFAULT_BAD_SCAN_PHRASES)
        out = [str(x).strip() for x in v if str(x).strip()]
        return out or list(DEFAULT_BAD_SCAN_PHRASES)

    @field_validator("wildcard_free_good_tag", "wildcard_trump_tag", mode="before")
    @classmethod
    def _normalize_wildcard(cls, v):  # noqa: ANN001
        if v is None or str(v).strip() == "":
            return None
        tag = normalize_rfid_tag(str(v))
        return tag


def load_room_settings(path: Path | None = None) -> RoomSettings:
    p = path or ROOM_SETTINGS_FILE
    if not p.exists():
        return RoomSettings()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return RoomSettings.model_validate(raw)
    except (json.JSONDecodeError, ValueError):
        return RoomSettings()


def save_room_settings(settings: RoomSettings, path: Path | None = None) -> RoomSettings:
    p = path or ROOM_SETTINGS_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(settings.model_dump(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return settings


def validate_room_settings_json(text: str) -> tuple[bool, str]:
    try:
        RoomSettings.model_validate_json(text)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"
    except ValueError as e:
        return False, str(e)
    return True, ""


def format_with_gm(template: str, gm_name: str) -> str:
    return template.replace("{gm}", gm_name)
