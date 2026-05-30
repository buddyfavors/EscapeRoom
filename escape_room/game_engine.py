from __future__ import annotations

import random
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from escape_room.models import (
    CodeAttemptResult,
    CodePools,
    DEFAULT_PUNISHMENT_LIMIT,
    Difficulty,
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
from escape_room.punishments_store import PunishmentEntry
from escape_room.rfid_format import normalize_rfid_tag


# Odds that a valid RFID scan is a "good" result vs "bad" (Gamemaster punishment).
GOOD_SCAN_CHANCE: dict[Difficulty, float] = {
    d: RFID_GOOD_PERCENT[d] / 100.0 for d in Difficulty
}

PUNISHMENT_LINES: tuple[str, ...] = (
    "Bad scan — the Gamemaster laughs.",
    "Punishment! The Gamemaster gains an edge.",
    "The Gamemaster savors that failure — no clue for you.",
    "Cursed tag. The house remembers.",
    "The Gamemaster claims that one with a grin.",
    "Wrong soul, right trap — try again when you stop shaking.",
    "The Gamemaster whispers: not today.",
    "That badge bled out — nothing earned.",
)

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
        self._listeners: list[Callable[[dict], None]] = []
        self._pending_slots: list[LockSlot] | None = None
        self._pending_counts: LockCounts | None = None
        self._punishments_limit: int = DEFAULT_PUNISHMENT_LIMIT
        self._punishments_received: int = 0
        self._last_punishment: str | None = None
        self._used_punishment_keys: set[str] = set()
        self._gm_won: bool = False
        self._rfid_consecutive_good_scans: int = 0

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
            if self._active is None or self._difficulty is None:
                return None
            locks = [slot.model_copy(deep=True) for slot in self._active]
            # `all([])` is True in Python — only declare a win when there is at least one lock.
            won = bool(locks) and all(s.solved for s in locks)
            gm_won = self._gm_won
            game_over = won or gm_won
            return GameSnapshot(
                difficulty=self._difficulty,
                locks=locks,
                started_at_iso=self._started_at.isoformat() if self._started_at else None,
                won=won,
                bad_codes_progress=self._bad_codes_streak,
                bad_codes_goal=BAD_CODE_STREAK_TRIGGER,
                punishments_received=self._punishments_received,
                punishments_limit=self._punishments_limit,
                last_punishment=self._last_punishment,
                gm_won=gm_won,
                game_over=game_over,
                good_rfid_progress=self._good_rfid_since_minigame,
                good_rfid_goal=MINIGAME_AFTER_GOOD_RFID,
                minigames_enabled=MINIGAMES_ENABLED,
                rfid_good_percent=RFID_GOOD_PERCENT.get(self._difficulty, 60),
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
        rng: random.Random | None = None,
    ) -> GameSnapshot:
        rng = rng or random.Random()
        with self._lock:
            pools = self._pools
            if (
                self._pending_slots is not None
                and self._pending_counts is not None
                and _counts_equal(self._pending_counts, lock_counts)
            ):
                slots = [slot.model_copy(deep=True) for slot in self._pending_slots]
            else:
                slots = build_slots_from_counts(lock_counts, pools, rng)
            self._pending_slots = None
            self._pending_counts = None
            self._active = slots
            self._difficulty = difficulty
            self._started_at = datetime.now(tz=timezone.utc)
            self._spent_tags.clear()
            self._bad_codes_streak = 0
            self._good_rfid_since_minigame = 0
            self._punishments_limit = max(1, int(punishment_limit))
            self._punishments_received = 0
            self._last_punishment = None
            self._used_punishment_keys.clear()
            self._gm_won = False
            self._rfid_consecutive_good_scans = 0
            snap = self.snapshot()
            assert snap is not None
            self._emit({"type": "game_started", "snapshot": snap.model_dump(mode="json")})
            return snap

    def stop(self) -> None:
        with self._lock:
            self._active = None
            self._difficulty = None
            self._started_at = None
            self._spent_tags.clear()
            self._bad_codes_streak = 0
            self._good_rfid_since_minigame = 0
            self._pending_slots = None
            self._pending_counts = None
            self._punishments_received = 0
            self._last_punishment = None
            self._used_punishment_keys.clear()
            self._gm_won = False
            self._rfid_consecutive_good_scans = 0
        self._emit({"type": "game_stopped"})

    def submit_code(self, raw: str) -> CodeAttemptResult:
        tag = normalize_rfid_tag(raw)
        if tag is not None:
            return self._submit_rfid(tag)
        return self._submit_lock_combination(raw)

    def _game_is_playable(self) -> bool:
        return self._active is not None and self._difficulty is not None and not self._gm_won

    def _base_bad_rfid_chance(self, difficulty: Difficulty) -> float:
        return 1.0 - GOOD_SCAN_CHANCE.get(difficulty, 0.60)

    def _current_bad_rfid_chance(self, difficulty: Difficulty) -> float:
        """PRD: bad odds rise after consecutive good RFID scans (caps at RFID_PRD_BAD_CAP)."""
        base = self._base_bad_rfid_chance(difficulty)
        increment = RFID_PRD_BAD_INCREMENT.get(difficulty, 0.09)
        bonus = self._rfid_consecutive_good_scans * increment
        return min(RFID_PRD_BAD_CAP, base + bonus)

    def _current_bad_rfid_chance_percent(self, difficulty: Difficulty) -> int:
        return round(self._current_bad_rfid_chance(difficulty) * 100)

    def _record_wheel_punishment(self, label: str) -> bool:
        """Apply one wheel punishment; return True if the Gamemaster just won."""
        self._punishments_received += 1
        self._last_punishment = label
        if self._punishments_received >= self._punishments_limit:
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

    def _submit_rfid(self, tag: str) -> CodeAttemptResult:
        bonus_minigame_url: str | None = None
        punishment_wheel_event: dict | None = None
        with self._lock:
            if not self._game_is_playable():
                if self._gm_won:
                    msg = "Game over — the Gamemaster wins. You failed to escape."
                elif not self._active or self._difficulty is None:
                    msg = "No active game."
                else:
                    msg = "No active game."
                result = CodeAttemptResult(
                    ok=False,
                    message=msg,
                    interaction="lock",
                )
                self._emit_code_result(result)
                return result

            if tag in self._spent_tags:
                result = CodeAttemptResult(
                    ok=False,
                    message="Already scanned — that tag is spent for this run. Try another badge.",
                    interaction="rfid_spent",
                )
                self._emit_code_result(result)
                return result

            if not self._rfid.has(tag):
                result = CodeAttemptResult(
                    ok=False,
                    message="Unknown RFID tag.",
                    interaction="rfid_unknown",
                )
                self._emit_code_result(result)
                return result

            rng = random.Random()
            difficulty = self._difficulty
            slots = self._active
            assert slots is not None

            result = self._roll_rfid_outcome(slots, difficulty, rng)
            self._spent_tags.add(tag)

            if result.interaction == "rfid_punishment":
                self._rfid_consecutive_good_scans = 0
                self._bad_codes_streak += 1
                triggered = self._bad_codes_streak >= BAD_CODE_STREAK_TRIGGER
                if triggered:
                    self._bad_codes_streak = 0
                    punishment_wheel_event = self._spin_punishment_wheel()
                    tail = " The wheel of punishments has spoken."
                else:
                    tail = (
                        f" ({self._bad_codes_streak}/{BAD_CODE_STREAK_TRIGGER} bad codes — "
                        "the Gamemaster is counting.)"
                    )
                result = result.model_copy(update={"message": result.message + tail})

            # Predictable minigame: every N good RFID rolls (only when arcade minigames are enabled).
            elif result.interaction in ("rfid_reveal", "rfid_exhausted"):
                self._rfid_consecutive_good_scans += 1
                if MINIGAMES_ENABLED:
                    self._good_rfid_since_minigame += 1
                    if self._good_rfid_since_minigame >= MINIGAME_AFTER_GOOD_RFID:
                        self._good_rfid_since_minigame = 0
                        slug = rng.choice(FORCED_MINIGAME_IDS)
                        bonus_minigame_url = f"/minigames/{slug}?forced=1&reason=three_clues"
                else:
                    self._good_rfid_since_minigame = 0

            self._emit_code_result(result)

        if punishment_wheel_event is not None:
            self._emit(punishment_wheel_event)
        if bonus_minigame_url:
            self._emit(
                {
                    "type": "forced_minigame",
                    "url": bonus_minigame_url,
                    "reason": "three_clues",
                    "message": "Three good RFID codes — the Gamemaster opens a minigame.",
                }
            )
        return result

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
                message=rng.choice(PUNISHMENT_LINES),
                interaction="rfid_punishment",
            )

        slot = _pick_lock_for_reveal(
            slots,
            kind_ok=lambda _k: True,
            difficulty=difficulty,
            rng=rng,
        )
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
            if not self._game_is_playable():
                if self._gm_won:
                    msg = "Game over — the Gamemaster wins. You failed to escape."
                else:
                    msg = "No active game."
                result = CodeAttemptResult(ok=False, message=msg, interaction="lock")
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
                    self._bad_codes_streak = 0
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
            triggered = self._bad_codes_streak >= BAD_CODE_STREAK_TRIGGER
            if triggered:
                self._bad_codes_streak = 0
                punishment_event = self._spin_punishment_wheel()

            tail = (
                " The wheel of punishments has spoken."
                if triggered
                else f" ({self._bad_codes_streak}/{BAD_CODE_STREAK_TRIGGER} bad codes — the Gamemaster is counting.)"
            )
            result = CodeAttemptResult(
                ok=False,
                message="That code does not open a lock." + tail,
                interaction="lock",
            )
            self._emit_code_result(result)

        if punishment_event is not None:
            self._emit(punishment_event)
        return result

    def _spin_punishment_wheel(self) -> dict:
        """
        Pick a random unused entry from the configured wheel. Returns the event dict to emit.
        """
        rng = random.Random()
        entry = self._pick_wheel_entry(rng)

        if entry is None or entry.kind == "minigame":
            if not MINIGAMES_ENABLED:
                message, label = self._pick_unique_fallback_text(rng)
                gm_won = self._record_wheel_punishment(label)
                event: dict = {
                    "type": "punishment_text",
                    "reason": "punishment_wheel",
                    "message": message,
                }
            else:
                slug_target = entry.target if entry else "random"
                slug = self._pick_unique_minigame_slug(
                    rng,
                    None if slug_target == "random" else slug_target,
                )
                label = f"Minigame: {slug.replace('-', ' ').title()}"
                gm_won = self._record_wheel_punishment(label)
                event = {
                    "type": "forced_minigame",
                    "url": f"/minigames/{slug}?forced=1&reason=punishment",
                    "reason": "punishment_wheel",
                    "message": "The Gamemaster locks the room — your penance is a minigame.",
                }
        else:
            gm_won = self._record_wheel_punishment(entry.message)
            event = {
                "type": "punishment_text",
                "reason": "punishment_wheel",
                "message": entry.message,
            }

        if gm_won:
            event["gm_won"] = True
            event["game_over_message"] = (
                f"The Gamemaster wins — {self._punishments_limit} punishments delivered. "
                "You failed to escape!"
            )
            if event.get("type") == "forced_minigame":
                event = {
                    "type": "punishment_text",
                    "reason": "punishment_wheel",
                    "message": event["game_over_message"],
                    "gm_won": True,
                    "game_over_message": event["game_over_message"],
                }
        return event
