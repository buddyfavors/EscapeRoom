"""Sanity check: Gamemaster console virtual RFID scans (bonus / reward / punishment)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from escape_room.game_engine import BAD_CODE_STREAK_TRIGGER, GameEngine
from escape_room.models import LockCounts, PunishmentResolution, RfidTagFile
from escape_room.room_settings_store import RoomSettings


def _engine() -> GameEngine:
    engine = GameEngine()
    engine.set_rfid_tags(RfidTagFile(tags=[]))
    engine.set_room_settings(RoomSettings(gamemaster_name="GM", reward_badge_tag="0012217025"))
    return engine


def test_virtual_scans() -> None:
    engine = _engine()
    engine.start(LockCounts(lock4=1, digit4=1))

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
    assert snap.punishment_resolution is PunishmentResolution.luck_test, (start_bad, snap)

    blocked = engine.submit_virtual_rfid("good")
    assert blocked.interaction == "rfid_punishment"
    assert "pending" in blocked.message.lower()


def _trigger_wheel(engine: GameEngine) -> None:
    while engine.snapshot().punishment_resolution is PunishmentResolution.none:
        engine.submit_virtual_rfid("bad")
    if engine.snapshot().punishment_resolution is PunishmentResolution.luck_test:
        engine.submit_virtual_badge("complete")
    assert engine.snapshot().punishment_resolution is PunishmentResolution.trump_window


def test_virtual_badges_skip_and_complete() -> None:
    engine = GameEngine()
    engine.set_room_settings(RoomSettings(gamemaster_name="GM"))
    events: list[dict] = []
    engine.subscribe(events.append)
    engine.start(LockCounts(lock4=1))

    nothing = engine.submit_virtual_badge("complete")
    assert not nothing.ok and "no punishment pending" in nothing.message.lower(), nothing
    assert engine.snapshot().punishment_resolution is PunishmentResolution.none

    _trigger_wheel(engine)
    skipped = engine.submit_virtual_badge("reward")
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


def test_physical_badges() -> None:
    engine = GameEngine()
    engine.set_rfid_tags(RfidTagFile(tags=["0000000001"]))
    engine.set_room_settings(
        RoomSettings(
            gamemaster_name="GM",
            reward_badge_tag="0000000002",
            gamemaster_complete_tag="0000000003",
        )
    )
    engine.start(LockCounts(lock4=1))

    immediate = engine.submit_code("0000000003")
    assert immediate.interaction == "rfid_punishment", immediate
    assert engine.snapshot().punishment_resolution is PunishmentResolution.trump_window

    skipped = engine.submit_code("0000000002")
    assert skipped.interaction == "wildcard_trump", skipped
    assert engine.snapshot().punishment_resolution is PunishmentResolution.none
    assert engine.snapshot().wildcard_free_good_cooldown_seconds == 0

    good = engine.submit_code("0000000002")
    assert good.ok and good.interaction == "rfid_reveal", good
    assert "guaranteed good scan" in good.message.lower(), good

    engine.submit_code("0000000003")
    done = engine.submit_code("0000000003")
    assert done.ok and "complete" in done.message.lower(), done


def test_legacy_badge_settings_migrate() -> None:
    old = RoomSettings.model_validate(
        {"wildcard_free_good_tag": "0012217025", "wildcard_trump_tag": "0012217025"}
    )
    assert old.reward_badge_tag == "0012217025", old
    skip_only = RoomSettings.model_validate({"wildcard_trump_tag": "0000000002"})
    assert skip_only.reward_badge_tag == "0000000002", skip_only
    assert "wildcard_trump_tag" not in old.model_dump()


if __name__ == "__main__":
    test_virtual_scans()
    test_virtual_badges_skip_and_complete()
    test_physical_badges()
    test_legacy_badge_settings_migrate()
    print("OK: gamemaster virtual scans verified")
