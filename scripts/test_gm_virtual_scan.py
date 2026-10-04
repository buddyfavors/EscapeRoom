"""Sanity check: Gamemaster console virtual RFID scans (bonus / reward / punishment)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from escape_room.game_engine import BAD_CODE_STREAK_TRIGGER, GameEngine
from escape_room.models import (
    BountyTheme,
    CodePools,
    Difficulty,
    GameMode,
    GamePhase,
    LockCounts,
    PunishmentResolution,
    RfidTagFile,
)
from escape_room.room_settings_store import RoomSettings


def _engine() -> GameEngine:
    engine = GameEngine()
    engine.set_pools(CodePools(digit3=["123", "456"], letter5=["APPLE"], digit4=["9876"]))
    engine.set_rfid_tags(RfidTagFile(tags=[]))
    engine.set_room_settings(RoomSettings(gamemaster_name="GM", wildcard_free_good_tag="0012217025"))
    return engine


def test_breakout_virtual_scans() -> None:
    engine = _engine()
    engine.start(Difficulty.hard, LockCounts(digit3=1, letter5=1), game_mode=GameMode.breakout)

    for _ in range(4):
        reward = engine.submit_virtual_rfid("good")
        assert reward.ok and reward.interaction == "rfid_reveal", reward

    bonus = engine.submit_virtual_rfid("roll")
    assert bonus.interaction in ("rfid_reveal", "rfid_punishment"), bonus

    snap = engine.snapshot()
    assert snap is not None
    start_bad = snap.bad_codes_progress
    for i in range(BAD_CODE_STREAK_TRIGGER):
        if engine.snapshot().punishment_resolution is not PunishmentResolution.none:
            break
        punish = engine.submit_virtual_rfid("bad")
        assert not punish.ok and punish.interaction == "rfid_punishment", punish
    snap = engine.snapshot()
    assert snap is not None
    assert snap.punishment_resolution is PunishmentResolution.trump_window, (start_bad, snap)

    blocked = engine.submit_virtual_rfid("good")
    assert blocked.interaction == "rfid_punishment"
    assert "pending" in blocked.message.lower()


def test_deadline_virtual_punishment_shaves_time() -> None:
    engine = _engine()
    engine.start(Difficulty.medium, LockCounts(), game_mode=GameMode.deadline, timer_minutes=10)
    for _ in range(BAD_CODE_STREAK_TRIGGER):
        r = engine.submit_virtual_rfid("bad")
        assert r.interaction == "rfid_punishment", r
    snap = engine.snapshot()
    assert snap is not None and snap.timer_seconds_remaining is not None
    assert snap.timer_seconds_remaining <= 10 * 60 - 30
    good = engine.submit_virtual_rfid("good")
    assert good.ok and good.interaction == "rfid_good", good
    engine.stop()


def test_bounty_virtual_scans_follow_batch_rules() -> None:
    engine = _engine()
    engine.start(
        Difficulty.medium,
        LockCounts(),
        game_mode=GameMode.bounty,
        rfids_per_punishment=2,
        good_codes_per_reward=1,
        rewards_to_win=5,
        bounty_theme=BountyTheme.breakout,
    )
    blocked = engine.submit_virtual_rfid("good")
    assert not blocked.ok and "reward badge" in blocked.message.lower(), blocked

    engine.submit_code("0012217025")
    assert engine.snapshot().phase is GamePhase.collection

    reward = engine.submit_virtual_rfid("good")
    assert reward.ok and "Reward earned" in reward.message, reward
    again = engine.submit_virtual_rfid("good")
    assert again.ok, again
    snap = engine.snapshot()
    assert snap is not None
    assert snap.rewards_earned == 2
    assert snap.phase is GamePhase.playing


def _trigger_wheel(engine: GameEngine) -> None:
    while engine.snapshot().punishment_resolution is PunishmentResolution.none:
        engine.submit_virtual_rfid("bad")


def test_virtual_badges_skip_and_complete() -> None:
    engine = GameEngine()
    engine.set_pools(CodePools(digit3=["123"]))
    engine.set_room_settings(RoomSettings(gamemaster_name="GM"))
    events: list[dict] = []
    engine.subscribe(events.append)
    engine.start(Difficulty.medium, LockCounts(digit3=1), game_mode=GameMode.breakout)

    nothing = engine.submit_virtual_badge("complete")
    assert not nothing.ok and "no punishment pending" in nothing.message.lower(), nothing
    assert engine.snapshot().punishment_resolution is PunishmentResolution.none
    nothing = engine.submit_virtual_badge("skip")
    assert not nothing.ok and "skip badge only works" in nothing.message.lower(), nothing

    _trigger_wheel(engine)
    skipped = engine.submit_virtual_badge("skip")
    assert skipped.ok and skipped.interaction == "wildcard_trump", skipped
    assert engine.snapshot().punishment_resolution is PunishmentResolution.none
    assert any(e["type"] == "trump_used" for e in events)
    assert engine.snapshot().punishments_received == 0

    _trigger_wheel(engine)
    done = engine.submit_virtual_badge("complete")
    assert done.ok and "complete" in done.message.lower(), done
    snap = engine.snapshot()
    assert snap.punishment_resolution is PunishmentResolution.none
    assert snap.punishments_received == 1


def test_virtual_reward_badge_without_configured_tag() -> None:
    engine = GameEngine()
    engine.set_room_settings(RoomSettings(gamemaster_name="GM"))
    engine.start(
        Difficulty.medium,
        LockCounts(),
        game_mode=GameMode.bounty,
        rfids_per_punishment=3,
        bounty_theme=BountyTheme.breakout,
    )
    badge = engine.submit_virtual_badge("reward")
    assert badge.ok and badge.interaction == "reward_badge", badge
    assert engine.snapshot().phase is GamePhase.collection


def test_physical_badges_unchanged() -> None:
    engine = GameEngine()
    engine.set_pools(CodePools(digit3=["123"]))
    engine.set_rfid_tags(RfidTagFile(tags=["0000000001"]))
    engine.set_room_settings(
        RoomSettings(
            gamemaster_name="GM",
            wildcard_trump_tag="0000000002",
            gamemaster_complete_tag="0000000003",
        )
    )
    engine.start(Difficulty.medium, LockCounts(digit3=1), game_mode=GameMode.breakout)

    immediate = engine.submit_code("0000000003")
    assert immediate.interaction == "rfid_punishment", immediate
    assert engine.snapshot().punishment_resolution is PunishmentResolution.trump_window

    skipped = engine.submit_code("0000000002")
    assert skipped.interaction == "wildcard_trump", skipped
    assert engine.snapshot().punishment_resolution is PunishmentResolution.none

    engine.submit_code("0000000003")
    done = engine.submit_code("0000000003")
    assert done.ok and "complete" in done.message.lower(), done


if __name__ == "__main__":
    test_breakout_virtual_scans()
    test_deadline_virtual_punishment_shaves_time()
    test_bounty_virtual_scans_follow_batch_rules()
    test_virtual_badges_skip_and_complete()
    test_virtual_reward_badge_without_configured_tag()
    test_physical_badges_unchanged()
    print("OK: gamemaster virtual scans verified")
