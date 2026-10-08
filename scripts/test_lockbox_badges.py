"""Sanity check: lockbox clues come after lock clues, and lockbox badges end the game."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from escape_room.game_engine import GameEngine
from escape_room.models import Difficulty, GameMode, LockCounts, RfidTagFile
from escape_room.room_settings_store import RoomSettings

BOX_A = "0000000101"
BOX_B = "0000000102"
BOX_C = "0000000103"


def _engine(lock4: int, digit4: int) -> GameEngine:
    engine = GameEngine()
    engine.set_rfid_tags(RfidTagFile(tags=[]))
    engine.set_room_settings(
        RoomSettings(gamemaster_name="GM", lockbox_tags=[BOX_A, BOX_B, BOX_C])
    )
    engine.start(
        Difficulty.medium,
        LockCounts(lock4=lock4, digit4=digit4),
        game_mode=GameMode.breakout,
    )
    return engine


def _reveal(engine: GameEngine, count: int) -> list[str]:
    kinds = []
    for _ in range(count):
        r = engine.submit_virtual_rfid("good")
        assert r.interaction == "rfid_reveal", r
        kinds.append(r.reveal["lock_kind"])
    return kinds


def test_locks_revealed_before_lockboxes() -> None:
    engine = _engine(lock4=2, digit4=2)
    snap = engine.snapshot()
    assert [s.kind for s in snap.locks] == ["lock4", "lock4", "digit4", "digit4"]
    kinds = _reveal(engine, 16)
    assert kinds[:8] == ["lock4"] * 8, kinds
    assert kinds[8:] == ["digit4"] * 8, kinds


def test_lockbox_badge_before_reveal_is_rejected_and_not_spent() -> None:
    engine = _engine(lock4=1, digit4=1)
    _reveal(engine, 4)
    early = engine.submit_code(BOX_A)
    assert not early.ok and "no lockbox code" in early.message.lower(), early
    _reveal(engine, 4)
    opened = engine.submit_code(BOX_A)
    assert opened.ok and opened.interaction == "lockbox_open" and opened.won, opened


def test_all_lockboxes_open_ends_game() -> None:
    engine = _engine(lock4=1, digit4=2)
    _reveal(engine, 8)
    first_box_id = next(
        s.id for s in engine.snapshot().locks if s.kind == "digit4" and all(s.revealed)
    )

    first = engine.submit_code(BOX_B)
    assert first.ok and not first.won and "(1/2)" in first.message, first
    assert first.lock_id == first_box_id

    reused = engine.submit_code(BOX_B)
    assert not reused.ok and reused.interaction == "rfid_spent", reused

    _reveal(engine, 4)
    second = engine.submit_code(BOX_C)
    assert second.ok and second.won, second
    snap = engine.snapshot()
    assert snap.won and snap.game_over
    assert not next(s for s in snap.locks if s.kind == "lock4").solved

    after = engine.submit_virtual_rfid("good")
    assert not after.ok and after.won, after


def test_partially_revealed_lockbox_can_be_opened() -> None:
    engine = _engine(lock4=0, digit4=2)
    _reveal(engine, 2)
    opened = engine.submit_code(BOX_A)
    assert opened.ok and not opened.won, opened
    kinds = _reveal(engine, 4)
    assert kinds == ["digit4"] * 4
    snap = engine.snapshot()
    remaining = [s for s in snap.locks if not s.solved]
    assert len(remaining) == 1 and all(remaining[0].revealed)


def test_virtual_lockbox_badge() -> None:
    engine = _engine(lock4=0, digit4=1)
    blocked = engine.submit_virtual_badge("lockbox")
    assert not blocked.ok, blocked
    _reveal(engine, 4)
    done = engine.submit_virtual_badge("lockbox")
    assert done.ok and done.won, done


def test_no_lockboxes_keeps_all_locks_rule() -> None:
    engine = _engine(lock4=1, digit4=0)
    _reveal(engine, 4)
    assert not engine.snapshot().won
    badge = engine.submit_code(BOX_A)
    assert not badge.ok and "no lockboxes" in badge.message.lower(), badge
    code = engine.snapshot().locks[0].code
    opened = engine.submit_code(code)
    assert opened.ok and opened.won, opened


def test_room_settings_normalize_lockbox_tags() -> None:
    s = RoomSettings.model_validate(
        {"lockbox_tags": [BOX_A, f" {BOX_A} ", "12345", "00-0000-0102"]}
    )
    assert s.lockbox_tags == [BOX_A, BOX_B], s.lockbox_tags


if __name__ == "__main__":
    test_locks_revealed_before_lockboxes()
    test_lockbox_badge_before_reveal_is_rejected_and_not_spent()
    test_all_lockboxes_open_ends_game()
    test_partially_revealed_lockbox_can_be_opened()
    test_virtual_lockbox_badge()
    test_no_lockboxes_keeps_all_locks_rule()
    test_room_settings_normalize_lockbox_tags()
    print("OK: lockbox badges verified")
