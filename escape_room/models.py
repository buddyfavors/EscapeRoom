from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class GameMode(str, Enum):
    """Which escape-room ruleset is active."""

    breakout = "breakout"
    deadline = "deadline"
    bounty = "bounty"


class BountyTheme(str, Enum):
    """How bad codes behave in Bounty mode."""

    breakout = "breakout"
    deadline = "deadline"


class GamePhase(str, Enum):
    """Deadline-mode cycle phase (other modes stay on playing)."""

    playing = "playing"
    punishment = "punishment"
    collection = "collection"


class PunishmentResolution(str, Enum):
    """Active punishment wheel flow (all modes)."""

    none = "none"
    trump_window = "trump_window"
    completing = "completing"


class Difficulty(str, Enum):
    """RFID PRD tier — how fast bad-scan odds rise after good scans (same base luck for all)."""

    easy = "easy"
    medium = "medium"
    hard = "hard"


LockKind = Literal["digit3", "letter5", "digit4"]

# Base RFID luck (same for every tier). Difficulty only changes PRD escalation below.
RFID_GOOD_PERCENT_BASE = 45
RFID_GOOD_PERCENT: dict[Difficulty, int] = {
    d: RFID_GOOD_PERCENT_BASE for d in Difficulty
}

# PRD: after each good RFID scan in a row, bad chance rises by this much (RFID-heavy runs).
RFID_PRD_BAD_INCREMENT: dict[Difficulty, float] = {
    Difficulty.easy: 0.07,
    Difficulty.medium: 0.11,
    Difficulty.hard: 0.14,
}
RFID_PRD_BAD_CAP = 0.92


DEFAULT_PUNISHMENT_LIMIT = 3
UNLIMITED_PUNISHMENT_LIMIT = 0
DEFAULT_PUNISHMENT_LIMIT_ENABLED = False
DEFAULT_TIMER_MINUTES = 10
DEFAULT_RFIDS_PER_PUNISHMENT = 4
DEFAULT_GOOD_CODES_PER_REWARD = 5
DEFAULT_REWARDS_TO_WIN = 5
DEADLINE_BAD_CODE_TIME_PENALTY_SEC = 30
DEFAULT_FINAL_COUNTDOWN_START_AFTER = 3
FINAL_COUNTDOWN_SHRINK_FACTOR = 0.9
MIN_TIMER_DURATION_SEC = 60
TRUMP_WINDOW_SEC = 60
PUNISHMENT_COMPLETE_SEC = 60
WHEEL_SPIN_UI_SEC = 4

GAME_MODE_LABELS: dict[GameMode, str] = {
    GameMode.breakout: "Breakout",
    GameMode.deadline: "Deadline",
    GameMode.bounty: "Bounty",
}


class LockCounts(BaseModel):
    """How many locks of each kind to use in one game run."""

    digit3: int = Field(default=0, ge=0)
    letter5: int = Field(default=0, ge=0)
    digit4: int = Field(default=0, ge=0)

    def total(self) -> int:
        return self.digit3 + self.letter5 + self.digit4


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
    game_mode: GameMode = GameMode.breakout
    phase: GamePhase = GamePhase.playing
    difficulty: Difficulty
    locks: list[LockSlot]
    started_at_iso: str | None = None
    won: bool = False
    timer_duration_sec: int | None = Field(
        default=None,
        description="Deadline mode: length of each countdown segment in seconds.",
    )
    timer_ends_at_iso: str | None = Field(
        default=None,
        description="Deadline mode: when the current playing-phase countdown hits zero (UTC ISO).",
    )
    timer_seconds_remaining: int | None = Field(
        default=None,
        description="Deadline mode: seconds left on the active countdown (computed server-side).",
    )
    deadline_cycle: int = Field(
        default=1,
        description="Deadline mode: current countdown round (1-based).",
    )
    final_countdown_enabled: bool = Field(
        default=False,
        description="Deadline mode: shrink timer 10% each cycle after start_after rounds.",
    )
    final_countdown_start_after: int = Field(
        default=DEFAULT_FINAL_COUNTDOWN_START_AFTER,
        description="Deadline mode: full-length rounds before Final Countdown shrink begins.",
    )
    gamemaster_name: str = Field(default="Gamemaster")
    punishment_resolution: PunishmentResolution = Field(
        default=PunishmentResolution.none,
        description="Trump skip window or punishment completion countdown.",
    )
    pending_punishment_label: str | None = Field(default=None)
    pending_punishment_message: str | None = Field(default=None)
    pending_punishment_is_minigame: bool = Field(default=False)
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
    wildcard_trump_used: bool = Field(
        default=False,
        description="True while skip badge is on cooldown.",
    )
    wildcard_free_good_cooldown_seconds: int = Field(
        default=0,
        description="Reward badge cooldown remaining in seconds.",
    )
    wildcard_skip_cooldown_seconds: int = Field(
        default=0,
        description="Skip badge cooldown remaining in seconds.",
    )
    rfids_per_punishment: int = Field(
        default=DEFAULT_RFIDS_PER_PUNISHMENT,
        description="Deadline mode: RFID scans required after each timer punishment.",
    )
    rfids_collected: int = Field(
        default=0,
        description="Deadline mode: RFIDs scanned so far in the current collection phase.",
    )
    bounty_theme: BountyTheme | None = Field(
        default=None,
        description="Bounty mode: how bad codes are penalized.",
    )
    good_codes_per_reward: int = Field(
        default=DEFAULT_GOOD_CODES_PER_REWARD,
        description="Bounty mode: good RFID rolls needed to earn one reward.",
    )
    good_codes_progress: int = Field(
        default=0,
        description="Bounty mode: progress toward the next reward.",
    )
    rewards_earned: int = Field(
        default=0,
        description="Bounty mode: rewards collected so far.",
    )
    rewards_to_win: int = Field(
        default=DEFAULT_REWARDS_TO_WIN,
        description="Bounty mode: rewards required for players to win.",
    )
    bad_code_effect: str = Field(
        default="wheel",
        description="UI hint: wheel | time_penalty | lose_progress",
    )
    rfid_good_percent: int = Field(
        default=45,
        description="Percent chance a valid RFID scan is good (reveals a clue); same base for all tiers.",
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
        description="Bad codes before the punishment wheel spins (every 3rd bad; counter never resets mid-game).",
    )
    punishments_received: int = Field(
        default=0,
        description="How many times the punishment wheel has landed this run.",
    )
    punishments_limit: int = Field(
        default=UNLIMITED_PUNISHMENT_LIMIT,
        description="Wheel punishments allowed before the Gamemaster wins (0 = unlimited; Breakout only).",
    )
    last_punishment: str | None = Field(
        default=None,
        description="Label for the most recent wheel punishment.",
    )
    gm_won: bool = Field(
        default=False,
        description="True when punishment limit is reached — players failed to escape.",
    )
    game_over: bool = Field(
        default=False,
        description="True when players escaped or the Gamemaster won.",
    )
    good_rfid_progress: int = Field(
        default=0,
        description="Good RFID rolls since last forced minigame (reveal or exhausted; not punishment).",
    )
    good_rfid_goal: int = Field(
        default=3,
        description="After this many good RFID rolls, a minigame is forced.",
    )
    minigames_enabled: bool = Field(
        default=True,
        description="When false, no minigames are launched (LED board not wired).",
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
        "rfid_collect",
        "rfid_good",
        "wildcard_good",
        "wildcard_trump",
    ] = "lock"
    reveal: dict[str, Any] | None = Field(
        default=None,
        description="When interaction is rfid_reveal: lock_id, index, character, lock_kind.",
    )
