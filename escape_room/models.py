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
    bad_codes_progress: int = Field(
        default=0,
        description="Consecutive bad outcomes: RFID punishment rolls and/or wrong lock combinations.",
    )
    bad_codes_goal: int = Field(
        default=3,
        description="Bad codes in a row before the punishment wheel spins (reset by good RFID or opening a lock).",
    )
    good_rfid_progress: int = Field(
        default=0,
        description="Good RFID rolls since last forced minigame (reveal or exhausted; not punishment).",
    )
    good_rfid_goal: int = Field(
        default=3,
        description="After this many good RFID rolls, a minigame is forced.",
    )


class RfidTagFile(BaseModel):
    """
    Flat list of valid 10-digit RFID tag IDs. Each scan against a known tag is
    consumed once; the game engine then rolls good vs bad on the fly.
    """

    tags: list[str] = Field(default_factory=list)

    @field_validator("tags", mode="before")
    @classmethod
    def _normalize_tags(cls, v):  # noqa: ANN001
        if not isinstance(v, list):
            return v
        seen: set[str] = set()
        out: list[str] = []
        for raw in v:
            s = str(raw).strip()
            d = "".join(c for c in s if c.isdigit())
            if len(d) > 10:
                d = d[-10:]
            if len(d) == 10 and d not in seen:
                seen.add(d)
                out.append(d)
        return out

    def has(self, tag: str) -> bool:
        return tag in self.tags


class CodeAttemptResult(BaseModel):
    ok: bool
    message: str
    lock_id: str | None = None
    won: bool = False
    interaction: Literal[
        "lock",
        "rfid_reveal",
        "rfid_punishment",
        "rfid_unknown",
        "rfid_spent",
        "rfid_exhausted",
    ] = "lock"
    reveal: dict[str, Any] | None = Field(
        default=None,
        description="When interaction is rfid_reveal: lock_id, index, character, lock_kind.",
    )
