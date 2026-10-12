"""Sanity check: physical wheel of punishments replaces the on-screen wheel."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from escape_room.game_engine import GameEngine
from escape_room.models import LockCounts, PunishmentResolution
from escape_room.punishments_store import PunishmentEntry
from escape_room.room_settings_store import RoomSettings, load_room_settings, save_room_settings


def _engine(events: list[dict]) -> GameEngine:
    engine = GameEngine()
    engine.set_punishments([PunishmentEntry(raw="Ten push-ups", message="Ten push-ups")])
    engine.set_room_settings(RoomSettings(gamemaster_name="GM", physical_wheel=True))
    engine.subscribe(events.append)
    return engine


def test_physical_wheel() -> None:
    events: list[dict] = []
    engine = _engine(events)
    engine.start(LockCounts(lock4=1))

    for _ in range(3):
        last = engine.submit_virtual_rfid("bad")
    assert "scratch-off" in last.message, last
    assert engine.snapshot().punishment_resolution is PunishmentResolution.luck_test
    assert not any(e["type"] == "punishment_wheel" for e in events)

    lost = engine.submit_virtual_badge("complete")
    assert lost.interaction == "luck_failure" and "GM spins the wheel" in lost.message, lost

    wheel = next(e for e in events if e["type"] == "punishment_wheel")
    assert wheel["physical"] is True
    assert wheel["entries"] == []
    assert wheel["punishment"]["label"] == "Spin the wheel!"
    assert "GM spins the wheel" in wheel["punishment"]["message"]

    snap = engine.snapshot()
    assert snap.punishment_resolution is PunishmentResolution.trump_window
    assert snap.pending_punishment_label == "Spin the wheel!"

    engine.submit_virtual_badge("complete")
    snap = engine.snapshot()
    assert snap.punishment_resolution is PunishmentResolution.none
    assert snap.punishments_received == 1
    done = next(e for e in events if e["type"] == "punishment_text")
    assert done["physical"] is True and "dealt" in done["message"]
    # The on-screen wheel list was never drawn from.
    assert "Ten push-ups" not in engine._used_punishment_keys


def test_setting_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "room.json"
        assert load_room_settings(path).physical_wheel is False
        save_room_settings(RoomSettings(physical_wheel=True), path)
        assert load_room_settings(path).physical_wheel is True


if __name__ == "__main__":
    test_physical_wheel()
    test_setting_round_trip()
    print("OK: physical wheel verified")
