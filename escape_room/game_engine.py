from __future__ import annotations

import random
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from escape_room.models import (
    CodeAttemptResult,
    DEFAULT_PUNISHMENT_LIMIT,
    UNLIMITED_PUNISHMENT_LIMIT,
    PunishmentResolution,
    GamePhase,
    GameSnapshot,
    LockCounts,
    LockKind,
    LockSlot,
    RfidTagFile,
    RFID_GOOD_PERCENT,
    RFID_PRD_BAD_CAP,
    RFID_PRD_BAD_INCREMENT,
    VirtualBadge,
    VirtualScanOutcome,
)
from escape_room.punishments_store import PunishmentEntry, split_punishment_display
from escape_room.rfid_format import normalize_rfid_tag
from escape_room.room_settings_store import (
    DEFAULT_BAD_SCAN_PHRASES,
    DEFAULT_GM_NAME,
    RoomSettings,
    format_with_gm,
)


# Odds that a valid RFID scan is a "good" result vs "bad" (Gamemaster punishment).
GOOD_SCAN_CHANCE = RFID_GOOD_PERCENT / 100.0

PUNISHMENT_LINES: tuple[str, ...] = DEFAULT_BAD_SCAN_PHRASES

BAD_CODE_STREAK_TRIGGER = 3
WILDCARD_COOLDOWN_SEC = 60
# Upper bound on how long badges count as "continue" when no screen reports the intro closed.
INTRO_MAX_SEC = 120

# On-screen wheel punishments used once every wheel line has been dealt (or the list is empty).
FALLBACK_PUNISHMENT_LINES: tuple[str, ...] = (
    "{gm} orders twenty jumping jacks, counted loud.",
    "Freeze for sixty seconds while {gm} circles.",
    "Everyone owes {gm} ten perfect push-ups before the next clue.",
    "Silence — nobody speaks until {gm} snaps.",
)


CODE_DIGITS = 4
MAX_UNIQUE_CODES = 10**CODE_DIGITS


def lock_kind_label(kind: LockKind) -> str:
    if kind == "lock4":
        return "4-digit lock"
    if kind == "digit4":
        return "4-digit lockbox"
    return kind


def build_slots_from_counts(counts: LockCounts, rng: random.Random) -> list[LockSlot]:
    """Generate a random 4-digit combination per lock, unique across every lock in the game.

    Regular locks come before lockboxes, matching the order their clues are earned.
    """
    total = counts.total()
    if total < 1:
        raise ValueError("Pick at least one lock to start the game.")
    if total > MAX_UNIQUE_CODES:
        raise ValueError(f"A game can have at most {MAX_UNIQUE_CODES} locks.")

    codes = iter(rng.sample(range(MAX_UNIQUE_CODES), total))
    slots: list[LockSlot] = []
    for kind in ("lock4", "digit4"):
        for _ in range(getattr(counts, kind)):
            slots.append(
                LockSlot(
                    id=str(uuid.uuid4()),
                    kind=kind,
                    code=f"{next(codes):0{CODE_DIGITS}d}",
                    solved=False,
                    revealed=[],
                )
            )
    return slots


def _counts_equal(a: LockCounts, b: LockCounts) -> bool:
    return a.lock4 == b.lock4 and a.digit4 == b.digit4


def _escape_targets(slots: list[LockSlot]) -> list[LockSlot]:
    """Locks that must open to win: every lockbox, or every lock when the game has no lockboxes."""
    lockboxes = [s for s in slots if s.kind == "digit4"]
    return lockboxes or list(slots)


def _players_escaped(slots: list[LockSlot]) -> bool:
    """Lockbox games end once every lockbox is open; otherwise every lock must be open."""
    if not slots:
        return False
    return all(s.solved for s in _escape_targets(slots))


def _matches(kind: LockKind, submitted: str, expected: str) -> bool:
    sub = submitted.strip()
    return sub.isdigit() and len(sub) == CODE_DIGITS and sub == expected.strip()


def _reveal_score(slot: LockSlot) -> int:
    return sum(1 for x in slot.revealed if x is not None)


def _apply_one_reveal(slot: LockSlot, rng: random.Random) -> tuple[int, str] | None:
    hidden = [i for i, ch in enumerate(slot.revealed) if ch is None]
    if not hidden:
        return None
    idx = rng.choice(hidden)
    char = slot.code[idx]
    slot.revealed[idx] = char
    return idx, char


class GameEngine:
    """Thread-safe session state for one escape room run."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rfid: RfidTagFile = RfidTagFile()
        self._punishments: list[PunishmentEntry] = []
        self._active: list[LockSlot] | None = None
        self._phase: GamePhase = GamePhase.playing
        self._started_at: datetime | None = None
        self._finished_at: datetime | None = None
        self._intro_until: datetime | None = None
        self._spent_tags: set[str] = set()
        self._bad_codes_streak: int = 0
        # The first good scan chooses a random lock; subsequent good scans keep
        # revealing that same lock until it is fully revealed.
        self._lock_in_progress_id: str | None = None
        # Lock ids in the order their codes became fully revealed; a lockbox reward opens
        # the earliest revealed lockbox since rewards aren't tied to a specific box.
        self._fully_revealed_order: list[str] = []
        self._listeners: list[Callable[[dict], None]] = []
        self._pending_slots: list[LockSlot] | None = None
        self._pending_counts: LockCounts | None = None
        self._punishments_limit: int = UNLIMITED_PUNISHMENT_LIMIT
        self._punishments_received: int = 0
        self._used_punishment_keys: set[str] = set()
        self._gm_won: bool = False
        self._rfid_consecutive_good_scans: int = 0
        self._room_settings: RoomSettings = RoomSettings()
        self._wildcard_free_good_ready_at: datetime | None = None
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

    def _cooldown_remaining_seconds(self, ready_at: datetime | None) -> int:
        if ready_at is None:
            return 0
        remaining = int((ready_at - datetime.now(tz=timezone.utc)).total_seconds())
        return max(0, remaining)

    def set_rfid_tags(self, tags: RfidTagFile) -> None:
        with self._lock:
            self._rfid = tags

    def set_punishments(self, entries: list[PunishmentEntry]) -> None:
        with self._lock:
            self._punishments = list(entries)

    def get_punishments(self) -> list[PunishmentEntry]:
        with self._lock:
            return list(self._punishments)

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
            if self._active is None:
                return None
            locks = [slot.model_copy(deep=True) for slot in self._active]
            won = _players_escaped(locks)
            gm_won = self._gm_won
            reward_cooldown_remaining = self._cooldown_remaining_seconds(
                self._wildcard_free_good_ready_at
            )
            return GameSnapshot(
                phase=self._phase,
                locks=locks,
                started_at_iso=self._started_at.isoformat() if self._started_at else None,
                intro_active=self._intro_active_locked(),
                finished_at_iso=self._finished_at.isoformat() if self._finished_at else None,
                won=won,
                gamemaster_name=self._gm_name(),
                punishment_resolution=self._punishment_resolution,
                pending_punishment_label=(
                    self._pending_punishment.get("label") if self._pending_punishment else None
                ),
                pending_punishment_message=(
                    self._pending_punishment.get("message") if self._pending_punishment else None
                ),
                punishment_timer_seconds_remaining=self._punishment_timer_seconds_remaining_locked(),
                punishment_timer_kind=self._punishment_timer_kind,
                wildcard_free_good_used=reward_cooldown_remaining > 0,
                wildcard_free_good_cooldown_seconds=reward_cooldown_remaining,
                bad_codes_progress=self._bad_codes_meter(),
                bad_codes_goal=BAD_CODE_STREAK_TRIGGER,
                punishments_received=self._punishments_received,
                punishments_limit=self._punishments_limit,
                gm_won=gm_won,
                game_over=won or gm_won,
                rfid_good_percent=RFID_GOOD_PERCENT,
                rfid_bad_chance_percent=self._current_bad_rfid_chance_percent(),
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
            slots = build_slots_from_counts(lock_counts, rng)
            self._pending_slots = [slot.model_copy(deep=True) for slot in slots]
            self._pending_counts = lock_counts.model_copy(deep=True)
            return [slot.model_copy(deep=True) for slot in slots]

    def start(
        self,
        lock_counts: LockCounts,
        punishment_limit: int = DEFAULT_PUNISHMENT_LIMIT,
        *,
        wait_for_badge: bool = False,
        rng: random.Random | None = None,
    ) -> GameSnapshot:
        """Set up a new game.

        With ``wait_for_badge`` the game stays in the ready phase (no clock, no scans)
        until the Gamemaster scans the reward badge or calls begin().
        """
        rng = rng or random.Random()
        with self._lock:
            if lock_counts.total() < 1:
                raise ValueError("Pick at least one lock to start the game.")
            if (
                self._pending_slots is not None
                and self._pending_counts is not None
                and _counts_equal(self._pending_counts, lock_counts)
            ):
                slots = [slot.model_copy(deep=True) for slot in self._pending_slots]
            else:
                slots = build_slots_from_counts(lock_counts, rng)
            self._pending_slots = None
            self._pending_counts = None
            self._active = slots
            self._phase = GamePhase.ready if wait_for_badge else GamePhase.playing
            self._started_at = None if wait_for_badge else datetime.now(tz=timezone.utc)
            self._finished_at = None
            self._intro_until = None
            self._spent_tags.clear()
            self._bad_codes_streak = 0
            self._lock_in_progress_id = None
            self._fully_revealed_order = []
            limit = int(punishment_limit)
            if limit <= 0:
                self._punishments_limit = UNLIMITED_PUNISHMENT_LIMIT
            else:
                self._punishments_limit = max(1, min(99, limit))
            self._punishments_received = 0
            self._used_punishment_keys.clear()
            self._gm_won = False
            self._rfid_consecutive_good_scans = 0
            self._wildcard_free_good_ready_at = None
            self._clear_punishment_resolution_locked()
            snap = self.snapshot()
            assert snap is not None
            event = "game_armed" if wait_for_badge else "game_started"
            self._emit({"type": event, "snapshot": snap.model_dump(mode="json")})
            return snap

    def begin(self) -> GameSnapshot | None:
        """Leave the ready phase and start play; None when no game is waiting to begin."""
        with self._lock:
            if self._active is None or self._phase is not GamePhase.ready:
                return None
            self._begin_locked()
            snap = self.snapshot()
            assert snap is not None
            self._emit({"type": "game_started", "snapshot": snap.model_dump(mode="json")})
            return snap

    def _begin_locked(self) -> None:
        self._phase = GamePhase.playing
        self._started_at = datetime.now(tz=timezone.utc)
        self._intro_until = self._started_at + timedelta(seconds=INTRO_MAX_SEC)

    def _intro_active_locked(self) -> bool:
        return self._intro_until is not None and datetime.now(tz=timezone.utc) < self._intro_until

    def _end_intro_locked(self) -> bool:
        was_active = self._intro_active_locked()
        self._intro_until = None
        if was_active:
            snap = self.snapshot()
            self._emit(
                {"type": "intro_done", "snapshot": snap.model_dump(mode="json") if snap else None}
            )
        return was_active

    def end_intro(self) -> bool:
        """The play screen closed the intro; False when no intro was showing."""
        with self._lock:
            return self._end_intro_locked()

    def _mark_finished_locked(self) -> None:
        if self._finished_at is None:
            self._finished_at = datetime.now(tz=timezone.utc)

    def stop(self) -> None:
        with self._lock:
            self._active = None
            self._phase = GamePhase.playing
            self._started_at = None
            self._finished_at = None
            self._intro_until = None
            self._spent_tags.clear()
            self._bad_codes_streak = 0
            self._lock_in_progress_id = None
            self._fully_revealed_order = []
            self._pending_slots = None
            self._pending_counts = None
            self._punishments_received = 0
            self._used_punishment_keys.clear()
            self._gm_won = False
            self._rfid_consecutive_good_scans = 0
            self._wildcard_free_good_ready_at = None
            self._clear_punishment_resolution_locked()
        self._emit({"type": "game_stopped"})

    def submit_code(self, raw: str) -> CodeAttemptResult:
        tag = normalize_rfid_tag(raw)
        if tag is not None:
            return self._submit_rfid(tag)
        return self._submit_lock_combination(raw)

    def submit_virtual_rfid(self, outcome: VirtualScanOutcome = "roll") -> CodeAttemptResult:
        """Gamemaster console: an approved RFID scan with no physical tag (never spent).

        "roll" uses the normal good/bad odds; "good" / "bad" force the outcome.
        """
        force = None if outcome == "roll" else outcome
        return self._submit_rfid(None, force=force)

    def submit_virtual_badge(self, badge: VirtualBadge) -> CodeAttemptResult:
        """Gamemaster console: scan the reward badge, Gamemaster badge, or a lockbox reward without a physical tag.

        Before the game begins, "reward" starts it; while the intro is on screen, "reward"
        and "complete" continue past it. During a scratch-off luck test, "reward"
        is a winning ticket and "complete" a losing one. While a punishment is pending,
        "reward" skips it. Unlike the physical Gamemaster badge, "complete" never triggers a
        punishment when none is pending.
        """
        return self._submit_rfid(None, badge=badge)

    def _bad_codes_meter(self) -> int:
        """Progress toward the next luck test (0–goal-1); never resets until a new game."""
        return self._bad_codes_streak % BAD_CODE_STREAK_TRIGGER

    def _bad_codes_streak_triggered(self) -> bool:
        return self._bad_codes_streak > 0 and self._bad_codes_streak % BAD_CODE_STREAK_TRIGGER == 0

    def _game_is_playable(self) -> bool:
        if self._active is None or self._gm_won:
            return False
        if self._phase is GamePhase.ready:
            return False
        if self._punishment_resolution is not PunishmentResolution.none:
            return False
        if _players_escaped(self._active):
            return False
        return True

    def _current_bad_rfid_chance(self) -> float:
        """PRD: bad odds rise after consecutive good RFID scans (caps at RFID_PRD_BAD_CAP)."""
        base = 1.0 - GOOD_SCAN_CHANCE
        bonus = self._rfid_consecutive_good_scans * RFID_PRD_BAD_INCREMENT
        return min(RFID_PRD_BAD_CAP, base + bonus)

    def _current_bad_rfid_chance_percent(self) -> int:
        return round(self._current_bad_rfid_chance() * 100)

    def _roll_is_bad(
        self,
        rng: random.Random,
        force: Literal["good", "bad"] | None,
    ) -> bool:
        if force is not None:
            return force == "bad"
        return rng.random() < self._current_bad_rfid_chance()

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
        labels = [entry.message for entry in self._punishments]
        return labels or ["Punishment"]

    def _begin_punishment_resolution_locked(self) -> dict:
        """Open the punishment window — virtual wheel pick, or a prompt to spin the physical wheel."""
        physical = self._room_settings.physical_wheel
        if physical:
            pending = {
                "kind": "physical",
                "label": "Spin the wheel!",
                "message": self._format_msg(
                    "{gm} spins the wheel of punishments."
                ),
            }
            display_entries: list[str] = []
            selected_index = 0
        else:
            pending, display_entries, selected_index = self._pick_virtual_wheel_punishment_locked()

        self._pending_punishment = pending
        self._punishment_resolution = PunishmentResolution.trump_window
        self._punishment_timer_kind = None
        self._punishment_timer_deadline = None
        self._schedule_punishment_timer_locked()

        return {
            "type": "punishment_wheel",
            "reason": "punishment_wheel",
            "physical": physical,
            "entries": display_entries,
            "selected_index": selected_index,
            "punishment": {
                "label": pending["label"],
                "message": pending["message"],
            },
        }

    def _pick_virtual_wheel_punishment_locked(self) -> tuple[dict[str, Any], list[str], int]:
        """Pick an on-screen wheel entry; returns (pending, display_entries, selected_index)."""
        rng = random.Random()
        entry = self._pick_wheel_entry(rng)
        display_entries = self._wheel_display_entries_locked()

        if entry is None:
            message = self._pick_unique_fallback_text(rng)
            pending = {"kind": "text", "label": message, "message": message}
            selected_label = message
        else:
            title, body = split_punishment_display(entry.message)
            pending = {"kind": "text", "label": title, "message": body}
            selected_label = entry.message

        selected_index = 0
        for i, label in enumerate(display_entries):
            if label == selected_label or pending["message"] == label:
                selected_index = i
                break
        else:
            display_entries = [selected_label, *display_entries]
            selected_index = 0

        return pending, display_entries, selected_index

    def _apply_pending_punishment_locked(self) -> dict:
        pending = self._pending_punishment
        self._clear_punishment_resolution_locked()
        if pending is None:
            return {"type": "punishment_resolved", "message": "Punishment cleared."}

        if self._record_wheel_punishment():
            msg = (
                f"{self._gm_name()} wins — {self._punishments_limit} punishments delivered. "
                "The prisoner stays bound!"
            )
            return {
                "type": "punishment_text",
                "reason": "punishment_wheel",
                "message": msg,
                "gm_won": True,
                "game_over_message": msg,
            }

        if pending["kind"] == "physical":
            return {
                "type": "punishment_text",
                "reason": "punishment_wheel",
                "physical": True,
                "message": "Punishment dealt — back to the game.",
            }
        return {
            "type": "punishment_text",
            "reason": "punishment_wheel",
            "message": pending["message"],
        }

    @staticmethod
    def _badge_matches(
        tag: str | None,
        configured: str | None,
        badge: VirtualBadge | None,
        kind: VirtualBadge,
    ) -> bool:
        if badge is not None:
            return badge == kind
        return tag is not None and bool(configured) and tag == configured

    def _try_skip_locked(self, matched: bool) -> CodeAttemptResult | None:
        if self._punishment_resolution is not PunishmentResolution.trump_window or not matched:
            return None
        self._clear_punishment_resolution_locked()
        return CodeAttemptResult(
            ok=True,
            message="Reward badge scanned — punishment skipped!",
            interaction="wildcard_trump",
        )

    def _try_gamemaster_complete_locked(self, matched: bool) -> dict | None:
        if self._punishment_resolution is not PunishmentResolution.trump_window or not matched:
            return None
        apply_event = self._apply_pending_punishment_locked()
        snap = self.snapshot()
        if apply_event is not None:
            apply_event["snapshot"] = snap.model_dump(mode="json") if snap else None
        return apply_event

    def _try_reward_badge_locked(self, matched: bool, rng: random.Random) -> CodeAttemptResult | None:
        if not matched:
            return None
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
        result = self._reveal_clue_locked(rng)
        return result.model_copy(
            update={"message": f"Reward badge — guaranteed good scan! {result.message}"}
        )

    def _reveal_clue_locked(self, rng: random.Random) -> CodeAttemptResult:
        """Good RFID result: reveal one character on the lock currently being worked on."""
        slots = self._active
        assert slots is not None
        slot = self._pick_lock_in_progress(slots, rng)
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
            self._lock_in_progress_id = None
            self._fully_revealed_order.append(slot.id)
        return CodeAttemptResult(
            ok=True,
            message=f'Working clue recovered: position {idx + 1} on a {lock_kind_label(slot.kind)} is "{char}".',
            interaction="rfid_reveal",
            reveal={
                "lock_id": slot.id,
                "lock_kind": slot.kind,
                "index": idx,
                "character": char,
            },
        )

    def _record_wheel_punishment(self) -> bool:
        """Apply one wheel punishment; return True if the Gamemaster just won."""
        self._punishments_received += 1
        if (
            self._punishments_limit > 0
            and self._punishments_received >= self._punishments_limit
        ):
            self._gm_won = True
            self._mark_finished_locked()
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

    def _pick_unique_fallback_text(self, rng: random.Random) -> str:
        lines = list(FALLBACK_PUNISHMENT_LINES)
        for line in rng.sample(lines, len(lines)):
            key = f"fallback:text:{line}"
            if key not in self._used_punishment_keys:
                self._reserve_punishment_key(key)
                return self._format_msg(line)
        return self._format_msg(rng.choice(lines))

    def _pick_lock_in_progress(self, slots: list[LockSlot], rng: random.Random) -> LockSlot | None:
        """Reveal one random lock at a time.

        The first good scan chooses a random eligible lock. Further good scans
        keep targeting that same lock until all clue positions are revealed.
        Lockboxes are only eligible once every regular lock is revealed or open.
        """
        candidates = [
            s
            for s in slots
            if not s.solved and any(x is None for x in s.revealed)
        ]
        if not candidates:
            return None
        regular = [s for s in candidates if s.kind != "digit4"]
        if regular:
            candidates = regular

        if self._lock_in_progress_id:
            for s in candidates:
                if s.id == self._lock_in_progress_id:
                    return s

        chosen = rng.choice(candidates)
        self._lock_in_progress_id = chosen.id
        return chosen

    def _submit_rfid(
        self,
        tag: str | None,
        *,
        force: Literal["good", "bad"] | None = None,
        badge: VirtualBadge | None = None,
    ) -> CodeAttemptResult:
        """Handle one RFID scan.

        ``tag=None`` is a virtual scan from the GM console: an approved tag, or the
        given ``badge`` regardless of which badge tags are configured in room settings.
        """
        punishment_event: dict | None = None
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
            if self._active is None:
                result = CodeAttemptResult(
                    ok=False,
                    message="No active game.",
                    interaction="lock",
                )
                self._emit_code_result(result)
                return result

            ws = self._room_settings
            is_reward = self._badge_matches(tag, ws.reward_badge_tag, badge, "reward")

            if self._phase is GamePhase.ready:
                if not is_reward:
                    result = CodeAttemptResult(
                        ok=False,
                        message=self._not_started_message(),
                        interaction="rfid_unknown",
                    )
                    self._emit_code_result(result)
                    return result
                self._begin_locked()
                snap = self.snapshot()
                assert snap is not None
                self._emit({"type": "game_started", "snapshot": snap.model_dump(mode="json")})
                return CodeAttemptResult(
                    ok=True,
                    message=self._format_msg("Reward badge scanned — {gm} starts the game!"),
                    interaction="game_begin",
                )

            is_complete = self._badge_matches(tag, ws.gamemaster_complete_tag, badge, "complete")
            if self._intro_active_locked():
                if is_reward or is_complete:
                    # The play screen closes the intro only once its text has finished.
                    self._emit({"type": "intro_continue"})
                    return CodeAttemptResult(
                        ok=True,
                        message="Badge scanned — continuing past the intro.",
                        interaction="intro_continue",
                    )
                self._end_intro_locked()

            if _players_escaped(self._active):
                result = CodeAttemptResult(
                    ok=False,
                    message="You already won — celebrate!",
                    interaction="rfid_good",
                    won=True,
                )
                self._emit_code_result(result)
                return result

            rng = random.Random()
            is_lockbox = (
                badge == "lockbox"
                if badge is not None
                else tag is not None and tag in ws.lockbox_tags
            )

            if self._punishment_resolution is PunishmentResolution.luck_test:
                if is_reward or is_complete:
                    result, luck_event = self._resolve_luck_test_locked(won=is_reward)
                    self._emit_code_result(result)
                    snap = self.snapshot()
                    luck_event["snapshot"] = snap.model_dump(mode="json") if snap else None
                    self._emit(luck_event)
                    return result
                if tag is not None and tag in self._spent_tags:
                    result = CodeAttemptResult(
                        ok=False,
                        message="Already scanned — that tag is spent for this run.",
                        interaction="rfid_spent",
                    )
                    self._emit_code_result(result)
                    return result
                result = CodeAttemptResult(
                    ok=False,
                    message=self._format_msg(
                        "Scratch-off pending — {gm} scans the reward badge for a winning "
                        "ticket or the punishment card for a losing one."
                    ),
                    interaction="rfid_punishment",
                )
                self._emit_code_result(result)
                return result

            if self._punishment_resolution is PunishmentResolution.trump_window:
                skipped = self._try_skip_locked(is_reward)
                if skipped is not None:
                    result = skipped
                    self._emit_code_result(result)
                    snap = self.snapshot()
                    self._emit(
                        {
                            "type": "trump_used",
                            "message": result.message,
                            "snapshot": snap.model_dump(mode="json") if snap else None,
                        }
                    )
                    return result
                completed = self._try_gamemaster_complete_locked(is_complete)
                if completed is not None:
                    self._emit(completed)
                    result = CodeAttemptResult(
                        ok=True,
                        message="Punishment marked complete.",
                        interaction="rfid_good",
                    )
                    self._emit_code_result(result)
                    return result
                if tag is not None and tag in self._spent_tags:
                    result = CodeAttemptResult(
                        ok=False,
                        message="Already scanned — that tag is spent for this run.",
                        interaction="rfid_spent",
                    )
                    self._emit_code_result(result)
                    return result
                result = CodeAttemptResult(
                    ok=False,
                    message=(
                        "Punishment pending — scan the reward badge to skip it, "
                        "or the Gamemaster badge to complete it."
                    ),
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

            if is_lockbox:
                result = self._open_lockbox_locked(tag)
                self._emit_code_result(result)
                return result

            # Physical Gamemaster badge with no punishment pending: trigger an immediate
            # punishment and reset the bad-code streak. (Pending case is handled above.)
            if is_complete:
                if badge is not None:
                    result = CodeAttemptResult(
                        ok=False,
                        message="No punishment pending — nothing to complete.",
                        interaction="rfid_unknown",
                    )
                    self._emit_code_result(result)
                    return result
                self._bad_codes_streak = 0
                punishment_event = self._spin_punishment_wheel()
                result = CodeAttemptResult(
                    ok=False,
                    message="Gamemaster badge scanned — immediate punishment triggered.",
                    interaction="rfid_punishment",
                )
                self._emit_code_result(result)
                snap = self.snapshot()
                punishment_event["snapshot"] = snap.model_dump(mode="json") if snap else None
                self._emit(punishment_event)
                return result

            reward = self._try_reward_badge_locked(is_reward, rng)
            if reward is not None:
                result = reward
                if result.interaction in ("rfid_reveal", "rfid_exhausted"):
                    self._rfid_consecutive_good_scans += 1
                self._emit_code_result(result)
            elif tag is not None and tag in self._spent_tags:
                result = CodeAttemptResult(
                    ok=False,
                    message="Already scanned — that tag is spent for this run. Try another badge.",
                    interaction="rfid_spent",
                )
                self._emit_code_result(result)
                return result
            elif tag is not None and not self._rfid.has(tag):
                result = CodeAttemptResult(
                    ok=False,
                    message="Unknown RFID tag.",
                    interaction="rfid_unknown",
                )
                self._emit_code_result(result)
                return result
            else:
                result = self._roll_rfid_outcome(rng, force)
                self._spend_tag_locked(tag)

                if result.interaction == "rfid_punishment":
                    self._rfid_consecutive_good_scans = 0
                    self._bad_codes_streak += 1
                    if self._bad_codes_streak_triggered():
                        punishment_event = self._begin_luck_test_locked()
                        tail = self._luck_test_tail()
                    else:
                        tail = (
                            f" ({self._bad_codes_meter()}/{BAD_CODE_STREAK_TRIGGER} broken clues — "
                            f"{self._gm_name()} is counting.)"
                        )
                    result = result.model_copy(update={"message": result.message + tail})
                else:
                    self._rfid_consecutive_good_scans += 1

                self._emit_code_result(result)

        if punishment_event is not None:
            snap = self.snapshot()
            punishment_event["snapshot"] = (
                snap.model_dump(mode="json") if snap else None
            )
            self._emit(punishment_event)
        assert result is not None
        return result

    def _spend_tag_locked(self, tag: str | None) -> None:
        if tag is not None:
            self._spent_tags.add(tag)

    def _lock_for_reward_locked(self, targets: list[LockSlot]) -> LockSlot | None:
        """Earliest fully revealed closed target, else the closed target with the most clues."""
        closed = [s for s in targets if not s.solved]
        by_id = {s.id: s for s in closed}
        for lock_id in self._fully_revealed_order:
            if lock_id in by_id:
                return by_id[lock_id]
        started = [s for s in closed if _reveal_score(s) > 0]
        if not started:
            return None
        return max(started, key=_reveal_score)

    def _open_lockbox_locked(self, tag: str | None) -> CodeAttemptResult:
        """Reward from inside a lockbox: mark that lockbox open (each reward once per game).

        Games without lockboxes treat every lock as a box with a reward inside.
        """
        if tag is not None and tag in self._spent_tags:
            return CodeAttemptResult(
                ok=False,
                message="That lockbox reward was already scanned this game.",
                interaction="rfid_spent",
            )
        slots = self._active
        assert slots is not None
        targets = _escape_targets(slots)
        noun = "lockbox" if any(s.kind == "digit4" for s in targets) else "lock"
        slot = self._lock_for_reward_locked(targets)
        if slot is None:
            return CodeAttemptResult(
                ok=False,
                message=f"No {noun} code has been revealed yet — keep earning clues.",
                interaction="rfid_unknown",
            )
        slot.solved = True
        self._spend_tag_locked(tag)
        if self._lock_in_progress_id == slot.id:
            self._lock_in_progress_id = None
        opened = sum(1 for s in targets if s.solved)
        won = _players_escaped(slots)
        if won:
            self._mark_finished_locked()
        msg = (
            f"Every {noun} is open — the prisoner is free!"
            if won
            else f"{noun.capitalize()} opened! ({opened}/{len(targets)})"
        )
        return CodeAttemptResult(
            ok=True,
            message=msg,
            lock_id=slot.id,
            won=won,
            interaction="lockbox_open",
        )

    def _not_started_message(self) -> str:
        return self._format_msg("The game hasn't started — {gm} scans the reward badge to begin.")

    def _game_over_message(self) -> str:
        if self._gm_won:
            return f"Game over — {self._gm_name()} wins."
        return "Game over."

    def _roll_rfid_outcome(
        self,
        rng: random.Random,
        force: Literal["good", "bad"] | None = None,
    ) -> CodeAttemptResult:
        """
        Valid RFID scan: roll good (random lock-code clue) vs bad (punishment).
        Uses PRD — bad chance rises after consecutive good scans (see RFID_PRD_BAD_INCREMENT).
        """
        if self._roll_is_bad(rng, force):
            return CodeAttemptResult(
                ok=False,
                message=self._pick_bad_scan_line(rng),
                interaction="rfid_punishment",
            )
        return self._reveal_clue_locked(rng)

    def _submit_lock_combination(self, raw: str) -> CodeAttemptResult:
        punishment_event: dict | None = None
        with self._lock:
            self._end_intro_locked()
            if self._punishment_resolution is not PunishmentResolution.none:
                result = CodeAttemptResult(
                    ok=False,
                    message=(
                        "Draw a scratch-off card first."
                        if self._punishment_resolution is PunishmentResolution.luck_test
                        else "Wait for the punishment wheel to finish."
                    ),
                    interaction="lock",
                )
                self._emit_code_result(result)
                return result

            if not self._game_is_playable():
                if self._gm_won:
                    msg = self._game_over_message()
                elif self._phase is GamePhase.ready:
                    msg = self._not_started_message()
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
                    won = _players_escaped(self._active)
                    msg = "Lockbox opened!" if slot.kind == "digit4" else "Lock opened!"
                    if won:
                        self._mark_finished_locked()
                        msg = (
                            "Every lockbox is open — the prisoner is free!"
                            if slot.kind == "digit4"
                            else "Every lock is open — the prisoner is free!"
                        )
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
            triggered = self._bad_codes_streak_triggered()
            punishment_event = None
            if triggered:
                punishment_event = self._begin_luck_test_locked()
                tail = self._luck_test_tail()
            else:
                tail = (
                    f" ({self._bad_codes_meter()}/{BAD_CODE_STREAK_TRIGGER} broken clues — "
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

    def _wheel_tail(self) -> str:
        if self._room_settings.physical_wheel:
            return self._format_msg(" Punishment time — {gm} spins the wheel.")
        return " The wheel of punishments has spoken."

    def _spin_punishment_wheel(self) -> dict:
        """Pick a wheel entry and open the punishment window."""
        return self._begin_punishment_resolution_locked()

    def _luck_test_tail(self) -> str:
        return self._format_msg(" Test your luck — draw a scratch-off card from {gm}'s bag.")

    def _begin_luck_test_locked(self) -> dict:
        """Bad-code streak hit: pause play until the Gamemaster scans the scratch-off result."""
        self._clear_punishment_resolution_locked()
        self._punishment_resolution = PunishmentResolution.luck_test
        return {
            "type": "luck_test",
            "message": self._format_msg(
                "Three broken clues — draw a scratch-off card from {gm}'s bag and test your luck!"
            ),
        }

    def _resolve_luck_test_locked(self, *, won: bool) -> tuple[CodeAttemptResult, dict]:
        """Winning ticket clears the luck test; a losing ticket spins the punishment wheel."""
        if won:
            self._clear_punishment_resolution_locked()
            result = CodeAttemptResult(
                ok=True,
                message="Winning ticket — no punishment this time!",
                interaction="luck_success",
            )
            return result, {"type": "luck_test_passed", "message": result.message}
        wheel = self._spin_punishment_wheel()
        result = CodeAttemptResult(
            ok=False,
            message="Losing ticket!" + self._wheel_tail(),
            interaction="luck_failure",
        )
        return result, wheel
