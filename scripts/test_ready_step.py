"""Sanity check: armed games wait for the reward badge, and wins record a finish time."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from escape_room.game_engine import GameEngine
from escape_room.models import GamePhase, LockCounts, RfidTagFile
from escape_room.room_settings_store import RoomSettings

TAG = "0000000001"
REWARD = "0000000900"
GM_BADGE = "0000000901"
BOX = "0000000101"


def _armed() -> tuple[GameEngine, list[dict]]:
    engine = GameEngine()
    engine.set_rfid_tags(RfidTagFile(tags=[TAG]))
    engine.set_room_settings(
        RoomSettings(
            gamemaster_name="GM",
            reward_badge_tag=REWARD,
            gamemaster_complete_tag=GM_BADGE,
            lockbox_tags=[BOX],
        )
    )
    events: list[dict] = []
    engine.subscribe(events.append)
    engine.start(LockCounts(lock4=0, digit4=1), wait_for_badge=True)
    return engine, events


def test_armed_game_waits_for_reward_badge() -> None:
    engine, events = _armed()
    snap = engine.snapshot()
    assert snap.phase is GamePhase.ready and snap.started_at_iso is None, snap
    assert [e["type"] for e in events] == ["game_armed"]

    for raw in (TAG, GM_BADGE, BOX, "1234"):
        r = engine.submit_code(raw)
        assert not r.ok and "hasn't started" in r.message, (raw, r)
    blocked = engine.submit_virtual_badge("complete")
    assert not blocked.ok, blocked
    assert engine.snapshot().phase is GamePhase.ready

    begun = engine.submit_code(REWARD)
    assert begun.ok and begun.interaction == "game_begin", begun
    snap = engine.snapshot()
    assert snap.phase is GamePhase.playing and snap.started_at_iso, snap
    assert events[-1]["type"] == "game_started"

    # The tag scanned while armed was not spent.
    r = engine.submit_code(TAG)
    assert r.interaction != "rfid_spent", r


def test_virtual_reward_badge_and_begin() -> None:
    engine, _ = _armed()
    r = engine.submit_virtual_badge("reward")
    assert r.ok and r.interaction == "game_begin", r
    assert engine.begin() is None

    engine, events = _armed()
    snap = engine.begin()
    assert snap is not None and snap.phase is GamePhase.playing
    assert events[-1]["type"] == "game_started"


def test_badges_continue_past_intro() -> None:
    engine, events = _armed()
    engine.submit_code(REWARD)
    assert engine.snapshot().intro_active

    for scan in (lambda: engine.submit_code(REWARD), lambda: engine.submit_code(GM_BADGE),
                 lambda: engine.submit_virtual_badge("reward")):
        r = scan()
        assert r.ok and r.interaction == "intro_continue", r
        assert events[-1] == {"type": "intro_continue"}, events[-1]
    snap = engine.snapshot()
    assert snap.intro_active and not snap.wildcard_free_good_used, snap
    assert not any(c for lock in snap.locks for c in lock.revealed), snap.locks

    assert engine.end_intro()
    assert events[-1]["type"] == "intro_done"
    assert not engine.snapshot().intro_active
    assert not engine.end_intro()

    r = engine.submit_code(REWARD)
    assert r.interaction == "rfid_reveal", r


def test_other_scan_ends_intro() -> None:
    engine, events = _armed()
    engine.begin()
    r = engine.submit_code(TAG)
    assert r.interaction in ("rfid_reveal", "rfid_punishment"), r
    assert "intro_done" in [e["type"] for e in events]
    assert not engine.snapshot().intro_active


def test_win_records_finish_time() -> None:
    engine, _ = _armed()
    engine.begin()
    for _ in range(4):
        engine.submit_virtual_rfid("good")
    assert engine.snapshot().finished_at_iso is None
    won = engine.submit_code(BOX)
    assert won.won, won
    snap = engine.snapshot()
    assert snap.won and snap.finished_at_iso and snap.finished_at_iso >= snap.started_at_iso
    engine.stop()
    engine.start(LockCounts(lock4=1))
    assert engine.snapshot().finished_at_iso is None


if __name__ == "__main__":
    test_armed_game_waits_for_reward_badge()
    test_virtual_reward_badge_and_begin()
    test_badges_continue_past_intro()
    test_other_scan_ends_intro()
    test_win_records_finish_time()
    print("OK: ready step, intro badges and finish time verified")
