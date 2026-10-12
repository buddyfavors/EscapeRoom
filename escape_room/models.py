from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class GamePhase(str, Enum):
    """The game starts in ``ready`` while the Gamemaster sets up the room; scanning the
    reward badge moves it to ``playing``.
    """

    ready = "ready"
    playing = "playing"


class PunishmentResolution(str, Enum):
    """Active punishment wheel flow (all modes)."""

    none = "none"
    # Bad-code streak hit: a player draws a scratch-off card; the Gamemaster scans the
    # reward badge (win — no punishment) or the Gamemaster badge (loss — wheel spins).
    luck_test = "luck_test"
    trump_window = "trump_window"
    completing = "completing"


LockKind = Literal["lock4", "digit4"]

# Gamemaster console virtual RFID: normal roll, guaranteed good, or guaranteed bad.
VirtualScanOutcome = Literal["roll", "good", "bad"]
# Gamemaster console virtual badges (same effect as the configured physical badge tags).
VirtualBadge = Literal["reward", "complete", "lockbox"]

RFID_GOOD_PERCENT = 45

# PRD: after each good RFID scan in a row, bad chance rises by this much (RFID-heavy runs).
RFID_PRD_BAD_INCREMENT = 0.11
RFID_PRD_BAD_CAP = 0.92


DEFAULT_PUNISHMENT_LIMIT = 3
UNLIMITED_PUNISHMENT_LIMIT = 0


class LockCounts(BaseModel):
    """How many locks of each kind to use in one game run."""

    lock4: int = Field(default=0, ge=0, description="4-digit combination locks")
    digit4: int = Field(default=0, ge=0, description="4-digit lockboxes")

    def total(self) -> int:
        return self.lock4 + self.digit4


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
    phase: GamePhase = GamePhase.playing
    locks: list[LockSlot]
    started_at_iso: str | None = Field(
        default=None,
        description="When play began (UTC ISO); None while the room is still in the ready phase.",
    )
    intro_active: bool = Field(
        default=False,
        description="The intro is on screen; the reward / Gamemaster badge continues past it.",
    )
    finished_at_iso: str | None = Field(
        default=None,
        description="When the players won or the Gamemaster won (UTC ISO).",
    )
    won: bool = Field(
        default=False,
        description="Every lockbox open (or every lock, when the game has no lockboxes).",
    )
    gamemaster_name: str = Field(default="Gamemaster")
    punishment_resolution: PunishmentResolution = Field(
        default=PunishmentResolution.none,
        description="Scratch-off luck test, trump skip window, or punishment completion countdown.",
    )
    pending_punishment_label: str | None = Field(default=None)
    pending_punishment_message: str | None = Field(default=None)
    punishment_timer_seconds_remaining: int | None = Field(
        default=None,
        description="Seconds left in trump window or completion phase.",
    )
    punishment_timer_kind: str | None = Field(
        default=None,
        description="trump or complete — which countdown is active.",
    )
    wildcard_free_good_used: bool = Field(
        default=False,
        description="True while reward badge is on cooldown.",
    )
    wildcard_free_good_cooldown_seconds: int = Field(
        default=0,
        description="Reward badge cooldown remaining in seconds.",
    )
    rfid_good_percent: int = Field(
        default=RFID_GOOD_PERCENT,
        description="Base percent chance a valid RFID scan is good (reveals a clue).",
    )
    rfid_bad_chance_percent: int = Field(
        default=55,
        description="Current bad-scan chance for the next RFID roll (PRD — rises after good scans).",
    )
    bad_codes_progress: int = Field(
        default=0,
        description="Consecutive bad outcomes: RFID punishment rolls and/or wrong lock combinations.",
    )
    bad_codes_goal: int = Field(
        default=3,
        description="Bad codes before a scratch-off luck test (every 3rd bad; counter never resets mid-game).",
    )
    punishments_received: int = Field(
        default=0,
        description="How many times the punishment wheel has landed this run.",
    )
    punishments_limit: int = Field(
        default=UNLIMITED_PUNISHMENT_LIMIT,
        description="Wheel punishments allowed before the Gamemaster wins (0 = unlimited).",
    )
    gm_won: bool = Field(
        default=False,
        description="True when punishment limit is reached — players failed to escape.",
    )
    game_over: bool = Field(
        default=False,
        description="True when players escaped or the Gamemaster won.",
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
        "rfid_good",
        "wildcard_trump",
        "luck_success",
        "luck_failure",
        "lockbox_open",
        "game_begin",
        "intro_continue",
    ] = "lock"
    reveal: dict[str, Any] | None = Field(
        default=None,
        description="When interaction is rfid_reveal: lock_id, index, character, lock_kind.",
    )
