"""Sanity check: Bounty reward badge starts collection, not guaranteed good scan."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from escape_room.game_engine import GameEngine
from escape_room.models import BountyTheme, Difficulty, GameMode, GamePhase, LockCounts, RfidTagFile
from escape_room.room_settings_store import RoomSettings


def test_bounty_reward_badge_starts_collection() -> None:
    engine = GameEngine()
    engine.set_rfid_tags(RfidTagFile(tags=["0011193681", "0001011547"]))
    engine.set_room_settings(
        RoomSettings(
            gamemaster_name="GM",
            wildcard_free_good_tag="0012217025",
        )
    )
    engine.start(
        difficulty=Difficulty.medium,
        lock_counts=LockCounts(),
        game_mode=GameMode.bounty,
        rfids_per_punishment=3,
        good_codes_per_reward=5,
        rewards_to_win=2,
        bounty_theme=BountyTheme.breakout,
    )

    snap = engine.snapshot()
    assert snap is not None
    assert snap.game_mode == GameMode.bounty
    assert snap.phase == GamePhase.playing

    blocked = engine.submit_code("0011193681")
    assert not blocked.ok
    assert "reward badge" in blocked.message.lower()

    badge = engine.submit_code("0012217025")
    assert badge.ok, badge.message
    assert badge.interaction == "reward_badge"
    assert "hand out 3 RFIDs!" in badge.message

    snap = engine.snapshot()
    assert snap is not None
    assert snap.phase == GamePhase.collection
    assert snap.rfids_collected == 0
    assert snap.good_codes_progress == 0

    scan1 = engine.submit_code("0011193681")
    assert scan1.interaction in ("rfid_good", "rfid_punishment")
    assert "(1/3 RFIDs scanned.)" in scan1.message

    print("OK: bounty reward badge flow verified")


if __name__ == "__main__":
    test_bounty_reward_badge_starts_collection()
