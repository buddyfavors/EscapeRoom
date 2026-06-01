from __future__ import annotations

import random
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from escape_room.models import (
    BountyTheme,
    CodeAttemptResult,
    CodePools,
    DEFAULT_GOOD_CODES_PER_REWARD,
    DEFAULT_PUNISHMENT_LIMIT,
    UNLIMITED_PUNISHMENT_LIMIT,
    DEFAULT_REWARDS_TO_WIN,
    DEFAULT_RFIDS_PER_PUNISHMENT,
    DEFAULT_TIMER_MINUTES,
    DEFAULT_FINAL_COUNTDOWN_START_AFTER,
    DEADLINE_BAD_CODE_TIME_PENALTY_SEC,
    FINAL_COUNTDOWN_SHRINK_FACTOR,
    MIN_TIMER_DURATION_SEC,
    PUNISHMENT_COMPLETE_SEC,
    PunishmentResolution,
    TRUMP_WINDOW_SEC,
    Difficulty,
    GameMode,
    GamePhase,
    GameSnapshot,
    LockCounts,
    LockKind,
    LockSlot,
    RfidTagFile,
    RFID_GOOD_PERCENT,
    RFID_PRD_BAD_CAP,
    RFID_PRD_BAD_INCREMENT,
)
from escape_room.config import MINIGAMES_ENABLED
from escape_room.punishments_store import PunishmentEntry, split_punishment_display
from escape_room.rfid_format import normalize_rfid_tag
from escape_room.room_settings_store import (
    DEFAULT_BAD_SCAN_PHRASES,
    DEFAULT_GM_NAME,
    RoomSettings,
    format_with_gm,
)


# Odds that a valid RFID scan is a "good" result vs "bad" (Gamemaster punishment).
GOOD_SCAN_CHANCE: dict[Difficulty, float] = {
    d: RFID_GOOD_PERCENT[d] / 100.0 for d in Difficulty
}

PUNISHMENT_LINES: tuple[str, ...] = DEFAULT_BAD_SCAN_PHRASES

# Minigames the "good-code surprise" trigger or the punishment wheel can launch.
# Must match the URL slugs registered in main.py. (Hangman is currently disabled.)
FORCED_MINIGAME_IDS: tuple[str, ...] = (
    "reaction-rush",
    "whack-mole",
    "rps",
    "simon",
    "pattern",
)

BAD_CODE_STREAK_TRIGGER = 3
WILDCARD_COOLDOWN_SEC = 60

DEADLINE_GOOD_LINES: tuple[str, ...] = (
    "Clean scan — the clock keeps ticking.",
    "Lucky badge — no penalty this time.",
    "{gm} grumbles, but the timer rolls on.",
    "Safe scan. Breathe and keep moving.",
)

BOUNTY_GOOD_LINES: tuple[str, ...] = (
    "Good code — one step closer to a reward.",
    "{gm} scowls — that one counts.",
    "Clean scan. Stack the wins.",
    "Another good code in the bank.",
)

# After this many "good" RFID rolls (not punishment), force a minigame (when MINIGAMES_ENABLED).
MINIGAME_AFTER_GOOD_RFID = 3

# When the wheel lands on a minigame but the arcade is disabled, use one of these instead.
WHEEL_MINIGAME_DISABLED_LINES: tuple[str, ...] = (
    "The LED board is dark — the Gamemaster orders twenty jumping jacks, counted loud.",
    "No buttons to bully you tonight — freeze for sixty seconds while the Gamemaster circles.",
    "Arcade offline — everyone owes the Gamemaster ten perfect push-ups before the next clue.",
    "The grid is asleep — trade a minigame for silence: nobody speaks until the Gamemaster snaps.",
)


def _kind_label(kind: LockKind) -> str:
    if kind == "digit3":
        return "3-digit lock"
    if kind == "digit4":
        return "4-digit lockbox"
    if kind == "letter5":
        return "5-letter lock"
    return kind


def _take_unique(pool: list[str], n: int, rng: random.Random) -> list[str]:
    if len(pool) < n:
        raise ValueError(f"Need at least {n} unique codes in pool, have {len(pool)}")
    return rng.sample(pool, n)


def build_slots_from_counts(
    counts: LockCounts,
    pools: CodePools,
    rng: random.Random,
) -> list[LockSlot]:
    """Pick random codes from configured pools; empty pool types are allowed if count is 0."""
    if counts.total() < 1:
        raise ValueError("Pick at least one lock to start the game.")

    slots: list[LockSlot] = []
    for kind in ("digit3", "letter5", "digit4"):
        n = getattr(counts, kind)
        if n == 0:
            continue
        pool = list(getattr(pools, kind))
        if n > len(pool):
            label = _kind_label(kind)
            raise ValueError(
                f"This game needs {n} {label}(s), but only {len(pool)} "
                f"{'is' if len(pool) == 1 else 'are'} configured in Settings."
            )
        codes = _take_unique(pool, n, rng)
        for code in codes:
            slots.append(
                LockSlot(
                    id=str(uuid.uuid4()),
                    kind=kind,
                    code=code,
                    solved=False,
                    revealed=[],
                )
            )

    random.shuffle(slots)
    return slots


def _counts_equal(a: LockCounts, b: LockCounts) -> bool:
    return a.digit3 == b.digit3 and a.letter5 == b.letter5 and a.digit4 == b.digit4


def _normalize_submitted(kind: LockKind, raw: str) -> str:
    s = raw.strip()
    if kind == "letter5":
        return s.upper()
    return s


def _matches(kind: LockKind, submitted: str, expected: str) -> bool:
    sub = _normalize_submitted(kind, submitted)
    exp = _normalize_submitted(kind, expected)
    if kind == "digit3":
        return sub.isdigit() and len(sub) == 3 and sub == exp
    if kind == "digit4":
        return sub.isdigit() and len(sub) == 4 and sub == exp
    if kind == "letter5":
        return len(sub) == 5 and sub.isalpha() and sub == exp
    return False


def _reveal_score(slot: LockSlot) -> int:
    return sum(1 for x in slot.revealed if x is not None)


def _pick_lock_for_reveal(
    slots: list[LockSlot],
    *,
    kind_ok: Callable[[LockKind], bool],
    difficulty: Difficulty,
    rng: random.Random,
) -> LockSlot | None:
    """
    Easy: focus clues on one lock (prefer the lock that already has the most reveals).
    Medium: mix of focus vs spread (50/50).
    Hard: uniform among eligible locks.
    """
    candidates = [
        s
        for s in slots
        if not s.solved and kind_ok(s.kind) and any(x is None for x in s.revealed)
    ]
    if not candidates:
        return None
    if difficulty is Difficulty.easy:
        return max(candidates, key=lambda s: (_reveal_score(s), s.id))
    if difficulty is Difficulty.medium:
        if rng.random() < 0.5:
            return max(candidates, key=lambda s: (_reveal_score(s), s.id))
        return min(candidates, key=lambda s: (_reveal_score(s), s.id))
    return rng.choice(candidates)


def _apply_one_reveal(slot: LockSlot, rng: random.Random) -> tuple[int, str] | None:
    hidden = [i for i, ch in enumerate(slot.revealed) if ch is None]
    if not hidden:
        return None
    idx = rng.choice(hidden)
    char = slot.code[idx]
    if slot.kind == "letter5":
        char = char.upper()
    slot.revealed[idx] = char
    return idx, char


class GameEngine:
    """Thread-safe session state for one escape room run."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pools: CodePools = CodePools()
        self._rfid: RfidTagFile = RfidTagFile()
        self._punishments: list[PunishmentEntry] = []
        self._active: list[LockSlot] | None = None
        self._difficulty: Difficulty | None = None
        self._started_at: datetime | None = None
        self._spent_tags: set[str] = set()
        self._bad_codes_streak: int = 0
        self._good_rfid_since_minigame: int = 0
        # Breakout UX: first good scan chooses a random lock; subsequent good scans
        # keep revealing that same lock until it is fully revealed.
        self._breakout_lock_in_progress_id: str | None = None
        self._listeners: list[Callable[[dict], None]] = []
        self._pending_slots: list[LockSlot] | None = None
        self._pending_counts: LockCounts | None = None
        self._punishments_limit: int = UNLIMITED_PUNISHMENT_LIMIT
        self._punishments_received: int = 0
        self._last_punishment: str | None = None
        self._used_punishment_keys: set[str] = set()
        self._gm_won: bool = False
        self._rfid_consecutive_good_scans: int = 0
        self._game_mode: GameMode | None = None
        self._phase: GamePhase = GamePhase.playing
        self._timer_duration_sec: int = DEFAULT_TIMER_MINUTES * 60
        self._timer_deadline: datetime | None = None
        self._timer_handle: threading.Timer | None = None
        self._rfids_per_punishment: int = DEFAULT_RFIDS_PER_PUNISHMENT
        self._rfids_collected: int = 0
        self._bounty_theme: BountyTheme | None = None
        self._good_codes_per_reward: int = DEFAULT_GOOD_CODES_PER_REWARD
        self._good_codes_progress: int = 0
        self._rewards_earned: int = 0
        self._rewards_to_win: int = DEFAULT_REWARDS_TO_WIN
        self._room_settings: RoomSettings = RoomSettings()
        self._timer_base_duration_sec: int = DEFAULT_TIMER_MINUTES * 60
        self._deadline_cycle: int = 1
        self._final_countdown_enabled: bool = False
        self._final_countdown_start_after: int = DEFAULT_FINAL_COUNTDOWN_START_AFTER
        self._wildcard_free_good_ready_at: datetime | None = None
        self._wildcard_skip_ready_at: datetime | None = None
        self._punishment_resolution: PunishmentResolution = PunishmentResolution.none
        self._punishment_timer_deadline: datetime | None = None
        self._punishment_timer_handle: threading.Timer | None = None
        self._punishment_timer_kind: str | None = None
        self._pending_punishment: dict[str, Any] | None = None

    def set_room_settings(self, settings: RoomSettings) -> None:
        with self._lock:
            self._room_settings = settings.model_copy(deep=True)

    def get_room_settings(self) -> RoomSettings:
        with self._lock:
            return self._room_settings.model_copy(deep=True)

    def _gm_name(self) -> str:
        return self._room_settings.gamemaster_name or DEFAULT_GM_NAME

    def _format_msg(self, template: str) -> str:
        return format_with_gm(template, self._gm_name())

    def _pick_bad_scan_line(self, rng: random.Random) -> str:
        phrases = self._room_settings.bad_scan_phrases or list(DEFAULT_BAD_SCAN_PHRASES)
        return self._format_msg(rng.choice(phrases))

    def _pick_good_line(self, lines: tuple[str, ...], rng: random.Random) -> str:
        return self._format_msg(rng.choice(lines))

    def _cooldown_remaining_seconds(self, ready_at: datetime | None) -> int:
        if ready_at is None:
            return 0
        remaining = int((ready_at - datetime.now(tz=timezone.utc)).total_seconds())
        return max(0, remaining)

    def set_pools(self, pools: CodePools) -> None:
        with self._lock:
            self._pools = pools

    def set_rfid_tags(self, tags: RfidTagFile) -> None:
        with self._lock:
            self._rfid = tags

    def set_punishments(self, entries: list[PunishmentEntry]) -> None:
        with self._lock:
            self._punishments = list(entries)

    def get_punishments(self) -> list[PunishmentEntry]:
        with self._lock:
            return list(self._punishments)

    def get_pools(self) -> CodePools:
        with self._lock:
            return self._pools.model_copy(deep=True)

    def get_rfid_tags(self) -> RfidTagFile:
        with self._lock:
            return self._rfid.model_copy(deep=True)

    def subscribe(self, fn: Callable[[dict], None]) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(fn)

        def unsubscribe() -> None:
            with self._lock:
                if fn in self._listeners:
                    self._listeners.remove(fn)

        return unsubscribe

    def _emit(self, event: dict) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            fn(event)

    def _emit_code_result(self, result: CodeAttemptResult) -> None:
        snap = self.snapshot()
        self._emit(
            {
                "type": "code_result",
                "result": result.model_dump(mode="json"),
                "snapshot": snap.model_dump(mode="json") if snap else None,
            }
        )

    def snapshot(self) -> GameSnapshot | None:
        with self._lock:
            if self._active is None or self._difficulty is None or self._game_mode is None:
                return None
            locks = [slot.model_copy(deep=True) for slot in self._active]
            mode = self._game_mode
            if mode is GameMode.breakout:
                won = bool(locks) and all(s.solved for s in locks)
            elif mode is GameMode.bounty:
                won = self._rewards_earned >= self._rewards_to_win
            else:
                won = False
            gm_won = self._gm_won
            game_over = won or gm_won
            timer_remaining = self._timer_seconds_remaining_locked()
            reward_cooldown_remaining = self._cooldown_remaining_seconds(
                self._wildcard_free_good_ready_at
            )
            skip_cooldown_remaining = self._cooldown_remaining_seconds(
                self._wildcard_skip_ready_at
            )
            return GameSnapshot(
                game_mode=mode,
                phase=self._phase,
                difficulty=self._difficulty,
                locks=locks,
                started_at_iso=self._started_at.isoformat() if self._started_at else None,
                won=won,
                timer_duration_sec=self._timer_duration_sec if mode is GameMode.deadline else None,
                timer_ends_at_iso=(
                    self._timer_deadline.isoformat()
                    if mode is GameMode.deadline and self._timer_deadline is not None
                    else None
                ),
                timer_seconds_remaining=timer_remaining,
                deadline_cycle=self._deadline_cycle if mode is GameMode.deadline else 1,
                final_countdown_enabled=(
                    self._final_countdown_enabled if mode is GameMode.deadline else False
                ),
                final_countdown_start_after=self._final_countdown_start_after,
                gamemaster_name=self._gm_name(),
                punishment_resolution=self._punishment_resolution,
                pending_punishment_label=(
                    self._pending_punishment.get("label") if self._pending_punishment else None
                ),
                pending_punishment_message=(
                    self._pending_punishment.get("message") if self._pending_punishment else None
                ),
                pending_punishment_is_minigame=bool(
                    self._pending_punishment and self._pending_punishment.get("kind") == "minigame"
                ),
                punishment_timer_seconds_remaining=self._punishment_timer_seconds_remaining_locked(),
                punishment_timer_kind=self._punishment_timer_kind,
                wildcard_free_good_used=reward_cooldown_remaining > 0,
                wildcard_trump_used=skip_cooldown_remaining > 0,
                wildcard_free_good_cooldown_seconds=reward_cooldown_remaining,
                wildcard_skip_cooldown_seconds=skip_cooldown_remaining,
                rfids_per_punishment=self._rfids_per_punishment,
                rfids_collected=self._rfids_collected,
                bounty_theme=self._bounty_theme,
                good_codes_per_reward=self._good_codes_per_reward,
                good_codes_progress=self._good_codes_progress,
                rewards_earned=self._rewards_earned,
                rewards_to_win=self._rewards_to_win,
                bad_code_effect=self._bad_code_effect_label(),
                bad_codes_progress=self._bad_codes_meter(),
                bad_codes_goal=BAD_CODE_STREAK_TRIGGER,
                punishments_received=self._punishments_received,
                punishments_limit=self._punishments_limit,
                last_punishment=self._last_punishment,
                gm_won=gm_won,
                game_over=game_over,
                good_rfid_progress=self._good_rfid_since_minigame,
                good_rfid_goal=MINIGAME_AFTER_GOOD_RFID,
                minigames_enabled=MINIGAMES_ENABLED,
                rfid_good_percent=RFID_GOOD_PERCENT.get(self._difficulty, 45),
                rfid_bad_chance_percent=self._current_bad_rfid_chance_percent(self._difficulty),
            )

    def preview_locks(
        self,
        lock_counts: LockCounts,
        rng: random.Random | None = None,
    ) -> list[LockSlot]:
        """Pick combinations for the next game without starting; stored until start() or a new preview."""
        rng = rng or random.Random()
        with self._lock:
            if self._active is not None:
                raise ValueError("Cannot preview locks while a game is running.")
            pools = self._pools
            slots = build_slots_from_counts(lock_counts, pools, rng)
            self._pending_slots = [slot.model_copy(deep=True) for slot in slots]
            self._pending_counts = lock_counts.model_copy(deep=True)
            return [slot.model_copy(deep=True) for slot in slots]

    def start(
        self,
        difficulty: Difficulty,
        lock_counts: LockCounts,
        punishment_limit: int = DEFAULT_PUNISHMENT_LIMIT,
        *,
        game_mode: GameMode = GameMode.breakout,
        timer_minutes: int = DEFAULT_TIMER_MINUTES,
        rfids_per_punishment: int = DEFAULT_RFIDS_PER_PUNISHMENT,
        good_codes_per_reward: int = DEFAULT_GOOD_CODES_PER_REWARD,
        rewards_to_win: int = DEFAULT_REWARDS_TO_WIN,
        bounty_theme: BountyTheme = BountyTheme.breakout,
        final_countdown_enabled: bool = False,
        final_countdown_start_after: int = DEFAULT_FINAL_COUNTDOWN_START_AFTER,
        rng: random.Random | None = None,
    ) -> GameSnapshot:
        rng = rng or random.Random()
        with self._lock:
            pools = self._pools
            if game_mode is GameMode.breakout:
                if lock_counts.total() < 1:
                    raise ValueError("Pick at least one lock to start Breakout.")
                if (
                    self._pending_slots is not None
                    and self._pending_counts is not None
                    and _counts_equal(self._pending_counts, lock_counts)
                ):
                    slots = [slot.model_copy(deep=True) for slot in self._pending_slots]
                else:
                    slots = build_slots_from_counts(lock_counts, pools, rng)
            else:
                slots = []
            self._pending_slots = None
            self._pending_counts = None
            self._active = slots
            self._game_mode = game_mode
            self._phase = GamePhase.playing
            self._difficulty = difficulty
            self._started_at = datetime.now(tz=timezone.utc)
            self._spent_tags.clear()
            self._bad_codes_streak = 0
            self._good_rfid_since_minigame = 0
            self._breakout_lock_in_progress_id = None
            if game_mode is GameMode.breakout:
                limit = int(punishment_limit)
                if limit <= 0:
                    self._punishments_limit = UNLIMITED_PUNISHMENT_LIMIT
                else:
                    self._punishments_limit = max(1, min(99, limit))
            else:
                self._punishments_limit = UNLIMITED_PUNISHMENT_LIMIT
            self._punishments_received = 0
            self._last_punishment = None
            self._used_punishment_keys.clear()
            self._gm_won = False
            self._rfid_consecutive_good_scans = 0
            self._rfids_per_punishment = max(1, min(99, int(rfids_per_punishment)))
            self._rfids_collected = 0
            self._bounty_theme = bounty_theme if game_mode is GameMode.bounty else None
            self._good_codes_per_reward = max(1, min(99, int(good_codes_per_reward)))
            self._good_codes_progress = 0
            self._rewards_earned = 0
            self._rewards_to_win = max(1, min(99, int(rewards_to_win)))
            self._wildcard_free_good_ready_at = None
            self._wildcard_skip_ready_at = None
            self._clear_punishment_resolution_locked()
            self._deadline_cycle = 1
            self._final_countdown_enabled = bool(final_countdown_enabled)
            self._final_countdown_start_after = max(1, min(99, int(final_countdown_start_after)))
            self._cancel_timer_locked()
            if game_mode is GameMode.deadline:
                minutes = max(1, min(180, int(timer_minutes)))
                self._timer_base_duration_sec = minutes * 60
                self._timer_duration_sec = self._compute_timer_duration_for_cycle_locked(1)
                self._start_timer_locked()
            snap = self.snapshot()
            assert snap is not None
            self._emit({"type": "game_started", "snapshot": snap.model_dump(mode="json")})
            return snap

    def stop(self) -> None:
        with self._lock:
            self._cancel_timer_locked()
            self._active = None
            self._difficulty = None
            self._game_mode = None
            self._phase = GamePhase.playing
            self._started_at = None
            self._spent_tags.clear()
            self._bad_codes_streak = 0
            self._good_rfid_since_minigame = 0
            self._breakout_lock_in_progress_id = None
            self._pending_slots = None
            self._pending_counts = None
            self._punishments_received = 0
            self._last_punishment = None
            self._used_punishment_keys.clear()
            self._gm_won = False
            self._rfid_consecutive_good_scans = 0
            self._timer_deadline = None
            self._rfids_collected = 0
            self._good_codes_progress = 0
            self._rewards_earned = 0
            self._bounty_theme = None
            self._wildcard_free_good_ready_at = None
            self._wildcard_skip_ready_at = None
            self._clear_punishment_resolution_locked()
            self._deadline_cycle = 1
        self._emit({"type": "game_stopped"})

    def submit_code(self, raw: str) -> CodeAttemptResult:
        tag = normalize_rfid_tag(raw)
        if tag is not None:
            return self._submit_rfid(tag)
        return self._submit_lock_combination(raw)

    def _bad_codes_meter(self) -> int:
        """Progress toward the next wheel spin (0–goal-1); never resets until a new game."""
        return self._bad_codes_streak % BAD_CODE_STREAK_TRIGGER

    def _bad_codes_wheel_triggered(self) -> bool:
        return self._bad_codes_streak > 0 and self._bad_codes_streak % BAD_CODE_STREAK_TRIGGER == 0

    def _game_is_playable(self) -> bool:
        if self._active is None or self._difficulty is None or self._gm_won:
            return False
        if self._punishment_resolution is not PunishmentResolution.none:
            return False
        if self._game_mode is GameMode.bounty and self._rewards_earned >= self._rewards_to_win:
            return False
        if (
            self._game_mode is GameMode.breakout
            and self._active
            and all(s.solved for s in self._active)
        ):
            return False
        return True

    def _base_bad_rfid_chance(self, difficulty: Difficulty) -> float:
        return 1.0 - GOOD_SCAN_CHANCE.get(difficulty, 0.45)

    def _current_bad_rfid_chance(self, difficulty: Difficulty) -> float:
        """PRD: bad odds rise after consecutive good RFID scans (caps at RFID_PRD_BAD_CAP)."""
        base = self._base_bad_rfid_chance(difficulty)
        increment = RFID_PRD_BAD_INCREMENT.get(difficulty, 0.11)
        bonus = self._rfid_consecutive_good_scans * increment
        return min(RFID_PRD_BAD_CAP, base + bonus)

    def _current_bad_rfid_chance_percent(self, difficulty: Difficulty) -> int:
        return round(self._current_bad_rfid_chance(difficulty) * 100)

    def _bad_code_effect_label(self) -> str:
        mode = self._game_mode
        if mode is GameMode.deadline:
            return "time_penalty"
        if mode is GameMode.bounty and self._bounty_theme is BountyTheme.deadline:
            return "lose_progress"
        return "wheel"

    def _cancel_timer_locked(self) -> None:
        handle = self._timer_handle
        self._timer_handle = None
        if handle is not None:
            handle.cancel()

    def _compute_timer_duration_for_cycle_locked(self, cycle: int) -> int:
        base = self._timer_base_duration_sec
        if not self._final_countdown_enabled or cycle <= self._final_countdown_start_after:
            return base
        shrink_steps = cycle - self._final_countdown_start_after
        duration = int(base * (FINAL_COUNTDOWN_SHRINK_FACTOR**shrink_steps))
        return max(MIN_TIMER_DURATION_SEC, duration)

    def _start_timer_locked(self) -> None:
        self._cancel_timer_locked()
        self._timer_duration_sec = self._compute_timer_duration_for_cycle_locked(self._deadline_cycle)
        self._timer_deadline = datetime.now(tz=timezone.utc) + timedelta(
            seconds=self._timer_duration_sec
        )
        self._schedule_timer_alarm_locked()

    def _schedule_timer_alarm_locked(self) -> None:
        self._cancel_timer_locked()
        if self._game_mode is not GameMode.deadline or self._phase is not GamePhase.playing:
            return
        if self._timer_deadline is None or self._gm_won:
            return
        delay = (self._timer_deadline - datetime.now(tz=timezone.utc)).total_seconds()
        if delay <= 0:
            delay = 0.0
        else:
            delay = min(delay, 1.0)
        self._timer_handle = threading.Timer(delay, self._timer_alarm_callback)
        self._timer_handle.daemon = True
        self._timer_handle.start()

    def _timer_seconds_remaining_locked(self) -> int | None:
        if self._game_mode is not GameMode.deadline:
            return None
        if self._phase is not GamePhase.playing or self._timer_deadline is None:
            return None
        remaining = int((self._timer_deadline - datetime.now(tz=timezone.utc)).total_seconds())
        return max(0, remaining)

    def _timer_alarm_callback(self) -> None:
        wheel_event: dict | None = None
        expired_snap: dict | None = None
        with self._lock:
            if (
                self._game_mode is not GameMode.deadline
                or self._phase is not GamePhase.playing
                or self._gm_won
                or self._timer_deadline is None
            ):
                return
            now = datetime.now(tz=timezone.utc)
            if now < self._timer_deadline:
                self._schedule_timer_alarm_locked()
                return
            self._timer_deadline = None
            self._cancel_timer_locked()
            wheel_event = self._deadline_timer_expired_locked()
            snap = self.snapshot()
            expired_snap = snap.model_dump(mode="json") if snap else None
        if wheel_event is not None:
            if wheel_event.get("type") == "punishment_wheel" and expired_snap is not None:
                wheel_event["snapshot"] = expired_snap
            self._emit(wheel_event)
        if expired_snap is not None:
            self._emit({"type": "timer_expired", "snapshot": expired_snap})

    def _deadline_timer_expired_locked(self) -> dict:
        return self._begin_punishment_resolution_locked(reason="timer")

    def _begin_collection_phase_locked(self) -> None:
        self._phase = GamePhase.collection
        self._rfids_collected = 0
        self._cancel_timer_locked()
        self._timer_deadline = None

    def _maybe_finish_collection_locked(self) -> bool:
        if self._rfids_collected < self._rfids_per_punishment:
            return False
        self._phase = GamePhase.playing
        self._rfids_collected = 0
        self._deadline_cycle += 1
        self._start_timer_locked()
        return True

    def _punishment_timer_seconds_remaining_locked(self) -> int | None:
        if self._punishment_resolution is PunishmentResolution.none:
            return None
        if self._punishment_timer_deadline is None:
            return None
        remaining = int(
            (self._punishment_timer_deadline - datetime.now(tz=timezone.utc)).total_seconds()
        )
        return max(0, remaining)

    def _cancel_punishment_timer_locked(self) -> None:
        handle = self._punishment_timer_handle
        self._punishment_timer_handle = None
        if handle is not None:
            handle.cancel()

    def _clear_punishment_resolution_locked(self) -> None:
        self._cancel_punishment_timer_locked()
        self._punishment_resolution = PunishmentResolution.none
        self._punishment_timer_deadline = None
        self._punishment_timer_kind = None
        self._pending_punishment = None

    def _schedule_punishment_timer_locked(self) -> None:
        # Punishments no longer auto-transition or auto-complete on timers.
        self._cancel_punishment_timer_locked()

    def _start_punishment_countdown_locked(self, kind: str, seconds: int) -> None:
        # Retained for backward compatibility; punishment window is now open-ended.
        self._punishment_timer_kind = None
        self._punishment_timer_deadline = None
        self._schedule_punishment_timer_locked()

    def _punishment_timer_callback(self) -> None:
        # Punishments no longer use countdown callbacks.
        return

    def _wheel_display_entries_locked(self) -> list[str]:
        labels: list[str] = []
        for entry in self._punishments:
            if entry.kind == "minigame":
                target = entry.target if entry.target != "random" else "minigame"
                labels.append(f"Minigame: {target.replace('-', ' ').title()}")
            else:
                labels.append(entry.message)
        if not labels:
            labels = ["Punishment"]
        return labels

    def _begin_punishment_resolution_locked(self, *, reason: str) -> dict:
        """Pick a wheel entry and open the punishment window."""
        rng = random.Random()
        entry = self._pick_wheel_entry(rng)
        display_entries = self._wheel_display_entries_locked()

        if entry is None or entry.kind == "minigame":
            if not MINIGAMES_ENABLED:
                message, label = self._pick_unique_fallback_text(rng)
                pending = {"kind": "text", "label": label, "message": message}
                selected_label = label
            else:
                slug_target = entry.target if entry else "random"
                slug = self._pick_unique_minigame_slug(
                    rng,
                    None if slug_target == "random" else slug_target,
                )
                label = f"Minigame: {slug.replace('-', ' ').title()}"
                pending = {
                    "kind": "minigame",
                    "label": label,
                    "message": self._format_msg(
                        "{gm} locks the room — your penance is a minigame."
                    ),
                    "slug": slug,
                }
                selected_label = label
        else:
            title, body = split_punishment_display(entry.message)
            pending = {
                "kind": "text",
                "label": title,
                "message": body,
                "record": entry.message,
            }
            selected_label = entry.message

        selected_index = 0
        for i, label in enumerate(display_entries):
            if label == selected_label or pending["message"] == label:
                selected_index = i
                break
        else:
            display_entries = [selected_label, *display_entries]
            selected_index = 0

        self._pending_punishment = pending
        self._punishment_resolution = PunishmentResolution.trump_window
        self._punishment_timer_kind = None
        self._punishment_timer_deadline = None
        self._schedule_punishment_timer_locked()

        if self._game_mode is GameMode.deadline:
            self._phase = GamePhase.punishment
            self._cancel_timer_locked()
            self._timer_deadline = None

        return {
            "type": "punishment_wheel",
            "reason": reason,
            "entries": display_entries,
            "selected_index": selected_index,
            "punishment": {
                "label": pending["label"],
                "message": pending["message"],
                "is_minigame": pending["kind"] == "minigame",
            },
        }

    def _apply_pending_punishment_locked(self) -> dict:
        pending = self._pending_punishment
        self._clear_punishment_resolution_locked()
        if pending is None:
            return {"type": "punishment_resolved", "message": "Punishment cleared."}

        record = pending.get("record") or pending["message"] or pending["label"]
        gm_won = self._record_wheel_punishment(record)
        gm = self._gm_name()

        if gm_won:
            if self._game_mode is GameMode.bounty:
                msg = f"{gm} wins — {self._punishments_limit} punishments delivered."
            elif self._game_mode is GameMode.deadline:
                msg = f"{gm} wins — {self._punishments_limit} timer punishments delivered."
            else:
                msg = (
                    f"{gm} wins — {self._punishments_limit} punishments delivered. "
                    "You failed to escape!"
                )
            return {
                "type": "punishment_text",
                "reason": "punishment_wheel",
                "message": msg,
                "gm_won": True,
                "game_over_message": msg,
            }

        if pending["kind"] == "minigame" and MINIGAMES_ENABLED:
            slug = pending.get("slug") or self._pick_unique_minigame_slug(random.Random())
            if self._game_mode is GameMode.deadline:
                self._phase = GamePhase.punishment
            return {
                "type": "forced_minigame",
                "url": f"/minigames/{slug}?forced=1&reason=punishment",
                "reason": "punishment_wheel",
                "message": pending["message"],
            }

        if self._game_mode is GameMode.deadline:
            self._begin_collection_phase_locked()

        return {
            "type": "punishment_text",
            "reason": "punishment_wheel",
            "message": pending["message"],
        }

    def _skip_pending_punishment_with_trump_locked(self) -> None:
        self._clear_punishment_resolution_locked()
        if self._game_mode is GameMode.deadline:
            self._phase = GamePhase.playing
            self._start_timer_locked()

    def _try_trump_skip_locked(self, tag: str) -> CodeAttemptResult | None:
        if self._punishment_resolution is not PunishmentResolution.trump_window:
            return None
        ws = self._room_settings
        if not ws.wildcard_trump_tag or tag != ws.wildcard_trump_tag:
            return None
        self._wildcard_skip_ready_at = None
        self._skip_pending_punishment_with_trump_locked()
        return CodeAttemptResult(
            ok=True,
            message=self._format_msg("Skip badge scanned — punishment skipped!"),
            interaction="wildcard_trump",
        )

    def _try_gamemaster_complete_locked(self, tag: str) -> dict | None:
        if self._punishment_resolution is not PunishmentResolution.trump_window:
            return None
        ws = self._room_settings
        if not ws.gamemaster_complete_tag or tag != ws.gamemaster_complete_tag:
            return None
        apply_event = self._apply_pending_punishment_locked()
        snap = self.snapshot()
        if apply_event is not None:
            apply_event["snapshot"] = snap.model_dump(mode="json") if snap else None
        return apply_event

    def _apply_deadline_time_penalty_locked(self) -> str:
        if self._timer_deadline is None:
            return " Time's already up — the wheel decides your fate."
        self._timer_deadline -= timedelta(seconds=DEADLINE_BAD_CODE_TIME_PENALTY_SEC)
        remaining = self._timer_seconds_remaining_locked() or 0
        self._schedule_timer_alarm_locked()
        return (
            f" Three bad codes — the clock shaves {DEADLINE_BAD_CODE_TIME_PENALTY_SEC}s "
            f"({remaining}s left)."
        )

    def _apply_bounty_bad_streak_locked(self) -> tuple[str, dict | None]:
        if self._bounty_theme is BountyTheme.deadline:
            if not self._bad_codes_wheel_triggered():
                return (
                    f" ({self._bad_codes_meter()}/{BAD_CODE_STREAK_TRIGGER} bad codes — "
                    f"{self._gm_name()} is counting.)",
                    None,
                )
            if self._good_codes_progress > 0:
                self._good_codes_progress -= 1
            return (
                self._format_msg(
                    " Three bad codes — {gm} steals one step toward your reward."
                ),
                None,
            )
        triggered = self._bad_codes_wheel_triggered()
        if triggered:
            return " The wheel of punishments has spoken.", self._spin_punishment_wheel()
        return (
            f" ({self._bad_codes_meter()}/{BAD_CODE_STREAK_TRIGGER} bad codes — "
            f"{self._gm_name()} is counting.)",
            None,
        )

    def _record_bounty_good_locked(self, rng: random.Random) -> CodeAttemptResult:
        msg = self._pick_good_line(BOUNTY_GOOD_LINES, rng)
        if MINIGAMES_ENABLED:
            self._good_rfid_since_minigame += 1
        self._good_codes_progress += 1
        won = False
        if self._good_codes_progress >= self._good_codes_per_reward:
            self._good_codes_progress = 0
            self._rewards_earned += 1
            msg = f"Reward earned! ({self._rewards_earned}/{self._rewards_to_win})"
            if self._rewards_earned >= self._rewards_to_win:
                won = True
                msg = f"All rewards claimed — you win! ({self._rewards_to_win}/{self._rewards_to_win})"
        else:
            msg += (
                f" ({self._good_codes_progress}/{self._good_codes_per_reward} toward next reward.)"
            )
        return CodeAttemptResult(
            ok=True,
            message=msg,
            interaction="rfid_good",
            won=won,
        )

    def complete_punishment(self) -> bool:
        """Deadline mode: minigame punishment finished — begin RFID collection."""
        snap_payload: dict | None = None
        with self._lock:
            if self._game_mode is not GameMode.deadline:
                return False
            if self._phase is not GamePhase.punishment or self._gm_won:
                return False
            self._begin_collection_phase_locked()
            snap = self.snapshot()
            snap_payload = snap.model_dump(mode="json") if snap else None
        if snap_payload is not None:
            self._emit({"type": "punishment_complete", "snapshot": snap_payload})
        return True

    def _force_good_rfid_locked(
        self,
        rng: random.Random,
        *,
        prefix: str,
    ) -> CodeAttemptResult:
        mode = self._game_mode
        difficulty = self._difficulty
        assert mode is not None and difficulty is not None
        if mode is GameMode.bounty:
            result = self._record_bounty_good_locked(rng)
            return result.model_copy(update={"message": f"{prefix} {result.message}"})
        if mode is GameMode.deadline:
            return CodeAttemptResult(
                ok=True,
                message=f"{prefix} {self._pick_good_line(DEADLINE_GOOD_LINES, rng)}",
                interaction="wildcard_good",
            )
        slots = self._active
        assert slots is not None
        result = self._roll_rfid_outcome_forced_good(slots, difficulty, rng)
        return result.model_copy(update={"message": f"{prefix} {result.message}"})

    def _try_wildcard_scan_locked(self, tag: str, rng: random.Random) -> CodeAttemptResult | None:
        ws = self._room_settings
        if ws.wildcard_free_good_tag and tag == ws.wildcard_free_good_tag:
            cooldown = self._cooldown_remaining_seconds(self._wildcard_free_good_ready_at)
            if cooldown > 0:
                return CodeAttemptResult(
                    ok=False,
                    message=f"Reward badge cooling down — try again in {cooldown}s.",
                    interaction="rfid_spent",
                )
            self._wildcard_free_good_ready_at = datetime.now(tz=timezone.utc) + timedelta(
                seconds=WILDCARD_COOLDOWN_SEC
            )
            return self._force_good_rfid_locked(
                rng,
                prefix="Reward badge — guaranteed good scan!",
            )
        return None

    def _roll_rfid_outcome_forced_good(
        self,
        slots: list[LockSlot],
        difficulty: Difficulty,
        rng: random.Random,
    ) -> CodeAttemptResult:
        slot = self._pick_lock_for_breakout_in_progress(slots, rng)
        if slot is None:
            return CodeAttemptResult(
                ok=True,
                message="Lucky scan — but every lock is already cracked or revealed.",
                interaction="rfid_exhausted",
            )
        applied = _apply_one_reveal(slot, rng)
        if applied is None:
            return CodeAttemptResult(
                ok=True,
                message="Lucky scan — nothing left to reveal on that lock.",
                interaction="rfid_exhausted",
            )
        idx, char = applied
        if all(x is not None for x in slot.revealed):
            self._breakout_lock_in_progress_id = None
        label = "letter" if slot.kind == "letter5" else "number"
        return CodeAttemptResult(
            ok=True,
            message=f'Clue earned: position {idx + 1} on a {label} lock is "{char}".',
            interaction="rfid_reveal",
            reveal={
                "lock_id": slot.id,
                "lock_kind": slot.kind,
                "index": idx,
                "character": char,
            },
        )

    def _record_wheel_punishment(self, label: str) -> bool:
        """Apply one wheel punishment; return True if the Gamemaster just won."""
        self._punishments_received += 1
        self._last_punishment = label
        if (
            self._punishments_limit > 0
            and self._punishments_received >= self._punishments_limit
        ):
            self._gm_won = True
            return True
        return False

    def _reserve_punishment_key(self, key: str) -> None:
        self._used_punishment_keys.add(key)

    def _pick_wheel_entry(self, rng: random.Random) -> PunishmentEntry | None:
        entries = list(self._punishments)
        available = [e for e in entries if e.raw not in self._used_punishment_keys]
        if not available:
            return None
        entry = rng.choice(available)
        self._reserve_punishment_key(entry.raw)
        return entry

    def _pick_unique_fallback_text(self, rng: random.Random) -> tuple[str, str]:
        for line in rng.sample(list(WHEEL_MINIGAME_DISABLED_LINES), len(WHEEL_MINIGAME_DISABLED_LINES)):
            key = f"fallback:text:{line}"
            if key not in self._used_punishment_keys:
                self._reserve_punishment_key(key)
                return line, line
        line = rng.choice(WHEEL_MINIGAME_DISABLED_LINES)
        return line, line

    def _pick_unique_minigame_slug(self, rng: random.Random, preferred: str | None = None) -> str:
        candidates = list(FORCED_MINIGAME_IDS)
        if preferred and preferred in candidates:
            key = f"minigame:{preferred}"
            if key not in self._used_punishment_keys:
                self._reserve_punishment_key(key)
                return preferred
        available = [s for s in candidates if f"minigame:{s}" not in self._used_punishment_keys]
        if not available:
            slug = rng.choice(candidates)
        else:
            slug = rng.choice(available)
        self._reserve_punishment_key(f"minigame:{slug}")
        return slug

    def _maybe_bonus_minigame_after_good_locked(self, rng: random.Random) -> str | None:
        mode = self._game_mode
        if not MINIGAMES_ENABLED:
            if mode is GameMode.breakout:
                self._good_rfid_since_minigame = 0
            return None
        if mode is GameMode.breakout:
            self._good_rfid_since_minigame += 1
            if self._good_rfid_since_minigame >= MINIGAME_AFTER_GOOD_RFID:
                self._good_rfid_since_minigame = 0
                slug = rng.choice(FORCED_MINIGAME_IDS)
                return f"/minigames/{slug}?forced=1&reason=three_clues"
        elif mode is GameMode.bounty:
            if self._good_rfid_since_minigame >= MINIGAME_AFTER_GOOD_RFID:
                self._good_rfid_since_minigame = 0
                slug = rng.choice(FORCED_MINIGAME_IDS)
                return f"/minigames/{slug}?forced=1&reason=three_clues"
        return None

    def _pick_lock_for_breakout_in_progress(self, slots: list[LockSlot], rng: random.Random) -> LockSlot | None:
        """Breakout: reveal one random lock at a time.

        The first good scan chooses a random eligible lock. Further good scans
        keep targeting that same lock until all clue positions are revealed.
        """
        candidates = [
            s
            for s in slots
            if not s.solved and any(x is None for x in s.revealed)
        ]
        if not candidates:
            return None

        if self._breakout_lock_in_progress_id:
            for s in candidates:
                if s.id == self._breakout_lock_in_progress_id:
                    return s

        chosen = rng.choice(candidates)
        self._breakout_lock_in_progress_id = chosen.id
        return chosen

    def _submit_rfid(self, tag: str) -> CodeAttemptResult:
        bonus_minigame_url: str | None = None
        punishment_wheel_event: dict | None = None
        phase_event: dict | None = None
        trump_used_event: dict | None = None
        result: CodeAttemptResult | None = None
        with self._lock:
            if self._gm_won:
                result = CodeAttemptResult(
                    ok=False,
                    message=self._game_over_message(),
                    interaction="lock",
                )
                self._emit_code_result(result)
                return result
            if self._active is None or self._difficulty is None:
                result = CodeAttemptResult(
                    ok=False,
                    message="No active game.",
                    interaction="lock",
                )
                self._emit_code_result(result)
                return result

            snap = self.snapshot()
            if snap and snap.won:
                result = CodeAttemptResult(
                    ok=False,
                    message="You already won — celebrate!",
                    interaction="rfid_good",
                    won=True,
                )
                self._emit_code_result(result)
                return result

            rng = random.Random()

            if self._punishment_resolution is PunishmentResolution.trump_window:
                trump = self._try_trump_skip_locked(tag)
                if trump is not None:
                    result = trump
                    self._emit_code_result(result)
                    trump_used_event = {
                        "type": "trump_used",
                        "message": result.message,
                        "snapshot": snap.model_dump(mode="json") if (snap := self.snapshot()) else None,
                    }
                    return result
                completed = self._try_gamemaster_complete_locked(tag)
                if completed is not None:
                    self._emit(completed)
                    result = CodeAttemptResult(
                        ok=True,
                        message="Punishment marked complete.",
                        interaction="rfid_good",
                    )
                    self._emit_code_result(result)
                    return result
                if tag in self._spent_tags:
                    result = CodeAttemptResult(
                        ok=False,
                        message="Already scanned — that tag is spent for this run.",
                        interaction="rfid_spent",
                    )
                    self._emit_code_result(result)
                    return result
                result = CodeAttemptResult(
                    ok=False,
                    message="Punishment pending — scan your skip badge or Gamemaster complete badge.",
                    interaction="rfid_punishment",
                )
                self._emit_code_result(result)
                return result

            if (
                self._phase is GamePhase.punishment
                and self._punishment_resolution is PunishmentResolution.none
            ):
                result = CodeAttemptResult(
                    ok=False,
                    message="Finish your punishment first — then you'll earn RFIDs to scan.",
                    interaction="rfid_punishment",
                )
                self._emit_code_result(result)
                return result

            if not self._game_is_playable():
                result = CodeAttemptResult(
                    ok=False,
                    message="No active game.",
                    interaction="lock",
                )
                self._emit_code_result(result)
                return result

            difficulty = self._difficulty
            mode = self._game_mode
            assert difficulty is not None
            ws = self._room_settings

            # Gamemaster badge behavior:
            # - if punishment pending: mark it complete.
            # - otherwise: trigger an immediate punishment and reset bad-code streak.
            if ws.gamemaster_complete_tag and tag == ws.gamemaster_complete_tag:
                completed = self._try_gamemaster_complete_locked(tag)
                if completed is not None:
                    self._emit(completed)
                    result = CodeAttemptResult(
                        ok=True,
                        message="Punishment marked complete.",
                        interaction="rfid_good",
                    )
                    self._emit_code_result(result)
                    return result
                if self._game_is_playable():
                    self._bad_codes_streak = 0
                    punishment_wheel_event = self._spin_punishment_wheel()
                    result = CodeAttemptResult(
                        ok=False,
                        message="Gamemaster badge scanned — immediate punishment triggered.",
                        interaction="rfid_punishment",
                    )
                    self._emit_code_result(result)
                    if punishment_wheel_event is not None:
                        snap = self.snapshot()
                        punishment_wheel_event["snapshot"] = (
                            snap.model_dump(mode="json") if snap else None
                        )
                        self._emit(punishment_wheel_event)
                    return result

            wildcard = self._try_wildcard_scan_locked(tag, rng)
            if wildcard is not None:
                result = wildcard
                if result.interaction in ("wildcard_good", "rfid_reveal", "rfid_exhausted", "rfid_good"):
                    self._rfid_consecutive_good_scans += 1
                    bonus_minigame_url = self._maybe_bonus_minigame_after_good_locked(rng)
                self._emit_code_result(result)
            elif tag in self._spent_tags:
                result = CodeAttemptResult(
                    ok=False,
                    message="Already scanned — that tag is spent for this run. Try another badge.",
                    interaction="rfid_spent",
                )
                self._emit_code_result(result)
                return result
            elif not self._rfid.has(tag):
                if ws.wildcard_trump_tag and tag == ws.wildcard_trump_tag:
                    result = CodeAttemptResult(
                        ok=False,
                        message="Skip badge only works while a punishment is pending.",
                        interaction="rfid_unknown",
                    )
                elif ws.gamemaster_complete_tag and tag == ws.gamemaster_complete_tag:
                    result = CodeAttemptResult(
                        ok=False,
                        message="Gamemaster complete badge only works while a punishment is pending.",
                        interaction="rfid_unknown",
                    )
                else:
                    result = CodeAttemptResult(
                        ok=False,
                        message="Unknown RFID tag.",
                        interaction="rfid_unknown",
                    )
                self._emit_code_result(result)
                return result
            elif mode is GameMode.deadline and self._phase is GamePhase.collection:
                self._spent_tags.add(tag)
                self._rfids_collected += 1
                need = self._rfids_per_punishment
                got = self._rfids_collected
                finished = self._maybe_finish_collection_locked()
                msg = f"RFID logged ({got}/{need})."
                if finished:
                    msg += f" All {need} scanned — the timer restarts!"
                    phase_event = {"type": "timer_restarted"}
                result = CodeAttemptResult(
                    ok=True,
                    message=msg,
                    interaction="rfid_collect",
                )
                self._emit_code_result(result)
            else:
                slots = self._active
                assert slots is not None

                if mode is GameMode.bounty:
                    result = self._roll_bounty_rfid_outcome(difficulty, rng)
                elif mode is GameMode.deadline:
                    result = self._roll_deadline_rfid_outcome(difficulty, rng)
                else:
                    result = self._roll_rfid_outcome(slots, difficulty, rng)

                self._spent_tags.add(tag)

                if result.interaction == "rfid_punishment":
                    self._rfid_consecutive_good_scans = 0
                    self._bad_codes_streak += 1
                    if mode is GameMode.deadline:
                        tail = self._apply_deadline_time_penalty_locked()
                    elif mode is GameMode.bounty:
                        tail, wheel = self._apply_bounty_bad_streak_locked()
                        if wheel is not None:
                            punishment_wheel_event = wheel
                            tail = " The wheel of punishments has spoken."
                    else:
                        triggered = self._bad_codes_wheel_triggered()
                        if triggered:
                            punishment_wheel_event = self._spin_punishment_wheel()
                            tail = " The wheel of punishments has spoken."
                        else:
                            tail = (
                                f" ({self._bad_codes_meter()}/{BAD_CODE_STREAK_TRIGGER} bad codes — "
                                f"{self._gm_name()} is counting.)"
                            )
                    result = result.model_copy(update={"message": result.message + tail})

                elif result.interaction in ("rfid_reveal", "rfid_exhausted", "rfid_good"):
                    self._rfid_consecutive_good_scans += 1
                    bonus_minigame_url = self._maybe_bonus_minigame_after_good_locked(rng)

                self._emit_code_result(result)

        if trump_used_event is not None:
            self._emit(trump_used_event)
        if punishment_wheel_event is not None:
            snap = self.snapshot()
            punishment_wheel_event["snapshot"] = (
                snap.model_dump(mode="json") if snap else None
            )
            self._emit(punishment_wheel_event)
        if bonus_minigame_url:
            self._emit(
                {
                    "type": "forced_minigame",
                    "url": bonus_minigame_url,
                    "reason": "three_clues",
                    "message": self._format_msg(
                        "Three good RFID codes — {gm} opens a minigame."
                    ),
                }
            )
        if phase_event is not None:
            snap = self.snapshot()
            phase_event["snapshot"] = snap.model_dump(mode="json") if snap else None
            self._emit(phase_event)
        assert result is not None
        return result

    def _game_over_message(self) -> str:
        gm = self._gm_name()
        if self._game_mode is GameMode.bounty and self._rewards_earned >= self._rewards_to_win:
            return "You won — all rewards claimed!"
        if self._gm_won:
            return f"Game over — {gm} wins."
        return "Game over."

    def _roll_deadline_rfid_outcome(
        self,
        difficulty: Difficulty,
        rng: random.Random,
    ) -> CodeAttemptResult:
        bad_chance = self._current_bad_rfid_chance(difficulty)
        if rng.random() < bad_chance:
            return CodeAttemptResult(
                ok=False,
                message=self._pick_bad_scan_line(rng),
                interaction="rfid_punishment",
            )
        return CodeAttemptResult(
            ok=True,
            message=self._pick_good_line(DEADLINE_GOOD_LINES, rng),
            interaction="rfid_good",
        )

    def _roll_bounty_rfid_outcome(
        self,
        difficulty: Difficulty,
        rng: random.Random,
    ) -> CodeAttemptResult:
        bad_chance = self._current_bad_rfid_chance(difficulty)
        if rng.random() < bad_chance:
            return CodeAttemptResult(
                ok=False,
                message=self._pick_bad_scan_line(rng),
                interaction="rfid_punishment",
            )
        return self._record_bounty_good_locked(rng)

    def _roll_rfid_outcome(
        self,
        slots: list[LockSlot],
        difficulty: Difficulty,
        rng: random.Random,
    ) -> CodeAttemptResult:
        """
        Valid RFID scan: roll good (random lock-code clue) vs bad (punishment).
        Uses PRD — bad chance rises after consecutive good scans (see RFID_PRD_BAD_INCREMENT).
        """
        bad_chance = self._current_bad_rfid_chance(difficulty)
        if rng.random() < bad_chance:
            return CodeAttemptResult(
                ok=False,
                message=self._pick_bad_scan_line(rng),
                interaction="rfid_punishment",
            )

        slot = self._pick_lock_for_breakout_in_progress(slots, rng)
        if slot is None:
            return CodeAttemptResult(
                ok=True,
                message="Lucky scan — but every lock is already cracked or revealed.",
                interaction="rfid_exhausted",
            )

        applied = _apply_one_reveal(slot, rng)
        if applied is None:
            return CodeAttemptResult(
                ok=True,
                message="Lucky scan — nothing left to reveal on that lock.",
                interaction="rfid_exhausted",
            )

        idx, char = applied
        if all(x is not None for x in slot.revealed):
            self._breakout_lock_in_progress_id = None
        label = "letter" if slot.kind == "letter5" else "number"
        return CodeAttemptResult(
            ok=True,
            message=f'Clue earned: position {idx + 1} on a {label} lock is "{char}".',
            interaction="rfid_reveal",
            reveal={
                "lock_id": slot.id,
                "lock_kind": slot.kind,
                "index": idx,
                "character": char,
            },
        )

    def _submit_lock_combination(self, raw: str) -> CodeAttemptResult:
        punishment_event: dict | None = None
        with self._lock:
            if self._punishment_resolution is not PunishmentResolution.none:
                result = CodeAttemptResult(
                    ok=False,
                    message="Wait for the punishment wheel to finish.",
                    interaction="lock",
                )
                self._emit_code_result(result)
                return result

            if not self._game_is_playable():
                if self._gm_won:
                    msg = self._game_over_message()
                else:
                    msg = "No active game."
                result = CodeAttemptResult(ok=False, message=msg, interaction="lock")
                self._emit_code_result(result)
                return result

            if self._game_mode is not GameMode.breakout:
                result = CodeAttemptResult(
                    ok=False,
                    message="This game mode has no locks — scan RFID badges instead.",
                    interaction="lock",
                )
                self._emit_code_result(result)
                return result

            submitted = raw.strip()
            if not submitted:
                result = CodeAttemptResult(ok=False, message="Empty code.", interaction="lock")
                self._emit_code_result(result)
                return result

            for slot in self._active:
                if slot.solved:
                    continue
                if _matches(slot.kind, submitted, slot.code):
                    slot.solved = True
                    won = all(s.solved for s in self._active)
                    msg = "Lock opened!"
                    if won:
                        msg = "All locks open — you escaped!"
                    result = CodeAttemptResult(
                        ok=True,
                        message=msg,
                        lock_id=slot.id,
                        won=won,
                        interaction="lock",
                    )
                    self._emit_code_result(result)
                    return result

            self._bad_codes_streak += 1
            triggered = self._bad_codes_wheel_triggered()
            punishment_event = None
            if triggered:
                punishment_event = self._spin_punishment_wheel()
                tail = " The wheel of punishments has spoken."
            else:
                tail = (
                    f" ({self._bad_codes_meter()}/{BAD_CODE_STREAK_TRIGGER} bad codes — "
                    f"{self._gm_name()} is counting.)"
                )
            result = CodeAttemptResult(
                ok=False,
                message="That code does not open a lock." + tail,
                interaction="lock",
            )
            self._emit_code_result(result)

        if punishment_event is not None:
            snap = self.snapshot()
            punishment_event["snapshot"] = snap.model_dump(mode="json") if snap else None
            self._emit(punishment_event)
        return result

    def _spin_punishment_wheel(self) -> dict:
        """Pick a wheel entry and start the trump skip window."""
        return self._begin_punishment_resolution_locked(reason="punishment_wheel")
