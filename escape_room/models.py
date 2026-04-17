from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Difficulty(str, Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


LockKind = Literal["digit3", "letter5", "digit4"]


class CodePools(BaseModel):
    """All redeemable lock codes loaded from the data file."""

    digit3: list[str] = Field(default_factory=list, description="3-digit combination locks")
    letter5: list[str] = Field(default_factory=list, description="5-letter combination locks")
    digit4: list[str] = Field(default_factory=list, description="4-digit lockbox codes")

    @field_validator("digit3", "digit4", mode="before")
    @classmethod
    def strip_digit_lists(cls, v):  # noqa: ANN001
        if not isinstance(v, list):
            return v
        return [str(x).strip() for x in v if str(x).strip()]

    @field_validator("letter5", mode="before")
    @classmethod
    def strip_upper_letters(cls, v):  # noqa: ANN001
        if not isinstance(v, list):
            return v
        return [str(x).strip().upper() for x in v if str(x).strip()]


class LockSlot(BaseModel):
    """One physical lock for the current session."""

    id: str
    kind: LockKind
    code: str
    solved: bool = False
    revealed: list[str | None] = Field(
        default_factory=list,
        description="Earned characters per position (None = still hidden). Same length as code.",
    )

    @model_validator(mode="after")
    def _pad_revealed(self) -> LockSlot:
        n = len(self.code)
        if len(self.revealed) != n:
            self.revealed = [None] * n
        return self


class GameSnapshot(BaseModel):
    difficulty: Difficulty
    locks: list[LockSlot]
    started_at_iso: str | None = None
    won: bool = False


RfidRewardKind = Literal["reveal_letter", "reveal_digit", "hint", "punishment"]


class RfidTagEntry(BaseModel):
    kind: RfidRewardKind
    message: str | None = Field(
        default=None,
        description="Optional text for hint or punishment entries.",
    )


class RfidTagFile(BaseModel):
    """Maps 10-digit tag IDs (string keys) to what scanning that tag does once per game."""

    tags: dict[str, RfidTagEntry] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: Any) -> Any:  # noqa: ANN401
        if not isinstance(data, dict):
            return data
        tags = data.get("tags")
        if not isinstance(tags, dict):
            return data
        norm: dict[str, Any] = {}
        for k, v in tags.items():
            key = str(k).strip()
            d = "".join(c for c in key if c.isdigit())
            if len(d) > 10:
                d = d[-10:]
            if len(d) == 10:
                norm[d] = v
        data = dict(data)
        data["tags"] = norm
        return data


class CodeAttemptResult(BaseModel):
    ok: bool
    message: str
    lock_id: str | None = None
    won: bool = False
    interaction: Literal[
        "lock",
        "rfid_reveal",
        "rfid_hint",
        "rfid_punishment",
        "rfid_unknown",
        "rfid_spent",
        "rfid_exhausted",
    ] = "lock"
    reveal: dict[str, Any] | None = Field(
        default=None,
        description="When interaction is rfid_reveal: lock_id, index, character, lock_kind.",
    )
