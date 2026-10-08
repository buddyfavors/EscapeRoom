"""Sanity check: every 3rd bad code starts a scratch-off luck test before any punishment."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from escape_room.game_engine import BAD_CODE_STREAK_TRIGGER, GameEngine
from escape_room.models import (
    BountyTheme,
    Difficulty,
    GameMode,
    LockCounts,
    PunishmentResolution,
    RfidTagFile,
)
from escape_room.punishments_store import PunishmentEntry
from escape_room.room_settings_store import RoomSettings

REWARD_TAG = "0000000011"
SKIP_TAG = "0000000012"
PUNISHMENT_CARD_TAG = "0000000013"
PLAYER_TAG = "0000000001"


def _engine(events: list[dict]) -> GameEngine:
    engine = GameEngine()
    engine.set_rfid_tags(RfidTagFile(tags=[PLAYER_TAG]))
    engine.set_punishments(
        [PunishmentEntry(raw="Ten push-ups", kind="text", target="Ten push-ups", message="Ten push-ups")]
    )
    engine.set_room_settings(
        RoomSettings(
            gamemaster_name="GM",
            wildcard_free_good_tag=REWARD_TAG,
            wildcard_trump_tag=SKIP_TAG,
            gamemaster_complete_tag=PUNISHMENT_CARD_TAG,
        )
    )
    engine.subscribe(events.append)
    return engine


def _three_bad(engine: GameEngine) -> None:
    for _ in range(BAD_CODE_STREAK_TRIGGER):
        engine.submit_virtual_rfid("bad")


def test_winning_ticket_skips_punishment() -> None:
    events: list[dict] = []
    engine = _engine(events)
    engine.start(Difficulty.medium, LockCounts(lock4=1), game_mode=GameMode.breakout)

    _three_bad(engine)
    snap = engine.snapshot()
    assert snap.punishment_resolution is PunishmentResolution.luck_test
    assert any(e["type"] == "luck_test" for e in events)
    assert not any(e["type"] == "punishment_wheel" for e in events)

    blocked = engine.submit_code(PLAYER_TAG)
    assert not blocked.ok and "scratch-off pending" in blocked.message.lower(), blocked
    skip = engine.submit_code(SKIP_TAG)
    assert not skip.ok and "scratch-off pending" in skip.message.lower(), skip
    combo = engine.submit_code("1234")
    assert not combo.ok and "scratch-off" in combo.message.lower(), combo
    assert engine.snapshot().punishment_resolution is PunishmentResolution.luck_test

    won = engine.submit_code(REWARD_TAG)
    assert won.ok and won.interaction == "luck_success", won
    snap = engine.snapshot()
    assert snap.punishment_resolution is PunishmentResolution.none
    assert snap.punishments_received == 0
    assert snap.wildcard_free_good_cooldown_seconds == 0
    assert any(e["type"] == "luck_test_passed" for e in events)
    assert not any(e["type"] == "punishment_wheel" for e in events)

    good = engine.submit_virtual_rfid("good")
    assert good.ok, good


def test_losing_ticket_runs_punishment_as_before() -> None:
    events: list[dict] = []
    engine = _engine(events)
    engine.start(Difficulty.medium, LockCounts(lock4=1), game_mode=GameMode.breakout)

    _three_bad(engine)
    lost = engine.submit_code(PUNISHMENT_CARD_TAG)
    assert not lost.ok and lost.interaction == "luck_failure", lost
    snap = engine.snapshot()
    assert snap.punishment_resolution is PunishmentResolution.trump_window
    assert snap.pending_punishment_label == "Ten push-ups"
    assert any(e["type"] == "punishment_wheel" for e in events)

    done = engine.submit_code(PUNISHMENT_CARD_TAG)
    assert done.ok and "complete" in done.message.lower(), done
    snap = engine.snapshot()
    assert snap.punishment_resolution is PunishmentResolution.none
    assert snap.punishments_received == 1


def test_losing_ticket_then_skip_badge() -> None:
    events: list[dict] = []
    engine = _engine(events)
    engine.start(Difficulty.medium, LockCounts(lock4=1), game_mode=GameMode.breakout)

    _three_bad(engine)
    engine.submit_virtual_badge("complete")
    skipped = engine.submit_code(SKIP_TAG)
    assert skipped.interaction == "wildcard_trump", skipped
    assert engine.snapshot().punishments_received == 0


def test_wrong_lock_combos_trigger_luck_test() -> None:
    events: list[dict] = []
    engine = _engine(events)
    engine.start(Difficulty.medium, LockCounts(lock4=1), game_mode=GameMode.breakout)
    code = engine._active[0].code
    wrong = f"{(int(code) + 1) % 10000:04d}"

    for _ in range(BAD_CODE_STREAK_TRIGGER):
        last = engine.submit_code(wrong)
    assert "scratch-off" in last.message, last
    assert engine.snapshot().punishment_resolution is PunishmentResolution.luck_test

    won = engine.submit_virtual_badge("reward")
    assert won.interaction == "luck_success", won


def test_bounty_breakout_theme_triggers_luck_test() -> None:
    events: list[dict] = []
    engine = _engine(events)
    engine.start(
        Difficulty.medium,
        LockCounts(),
        game_mode=GameMode.bounty,
        rfids_per_punishment=10,
        bounty_theme=BountyTheme.breakout,
    )
    engine.submit_virtual_badge("reward")
    _three_bad(engine)
    assert engine.snapshot().punishment_resolution is PunishmentResolution.luck_test

    lost = engine.submit_virtual_badge("complete")
    assert lost.interaction == "luck_failure", lost
    assert engine.snapshot().punishment_resolution is PunishmentResolution.trump_window


if __name__ == "__main__":
    test_winning_ticket_skips_punishment()
    test_losing_ticket_runs_punishment_as_before()
    test_losing_ticket_then_skip_badge()
    test_wrong_lock_combos_trigger_luck_test()
    test_bounty_breakout_theme_triggers_luck_test()
    print("OK: scratch-off luck test verified")
