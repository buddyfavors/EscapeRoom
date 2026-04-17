from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from fastapi import WebSocket

from escape_room.minigames.button_grid import BUTTON_COLORS, NUM_BUTTONS, color_name

logger = logging.getLogger(__name__)


def _difficulty_params(diff: str) -> dict[str, Any]:
    """
    Pattern Match: memorize a sequence of individual grid buttons (not just colors),
    then reproduce it in order in one pass.
    """
    diff = (diff or "medium").lower()
    if diff == "easy":
        return {"start_len": 3, "win_rounds": 5, "grow": 1, "step_ms": 700, "input_timeout_s": 6.0, "lives": 2}
    if diff == "hard":
        return {"start_len": 4, "win_rounds": 8, "grow": 2, "step_ms": 400, "input_timeout_s": 3.5, "lives": 1}
    return {"start_len": 3, "win_rounds": 6, "grow": 1, "step_ms": 550, "input_timeout_s": 5.0, "lives": 1}


async def run_pattern_session(ws: WebSocket) -> None:
    first = await ws.receive_json()
    if first.get("action") != "start":
        await ws.send_json({"type": "error", "message": 'Send {"action":"start"} first.'})
        return

    diff = str(first.get("difficulty", "medium")).lower()
    p = _difficulty_params(diff)
    rng = random.Random()
    cleared = 0
    lives = p["lives"]
    length = p["start_len"]

    await ws.send_json(
        {
            "type": "started",
            "difficulty": diff,
            "win_rounds": p["win_rounds"],
            "lives": lives,
            "colors": list(BUTTON_COLORS),
            "step_ms": p["step_ms"],
        }
    )

    try:
        while cleared < p["win_rounds"] and lives > 0:
            sequence = [rng.randrange(NUM_BUTTONS) for _ in range(length)]
            pattern = [{"i": i, "color": color_name(i)} for i in sequence]

            await ws.send_json(
                {
                    "type": "show_pattern",
                    "pattern": pattern,
                    "step_ms": p["step_ms"],
                    "round": cleared + 1,
                    "length": length,
                    "lives": lives,
                }
            )

            pressed: list[int] = []
            failed = False
            while len(pressed) < length:
                try:
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=p["input_timeout_s"])
                except asyncio.TimeoutError:
                    await ws.send_json(
                        {"type": "timeout", "expected": sequence[len(pressed)], "at": len(pressed)}
                    )
                    failed = True
                    break

                if msg.get("action") == "ping":
                    continue
                if msg.get("action") != "press":
                    continue

                try:
                    btn = int(msg.get("button"))
                except (TypeError, ValueError):
                    continue
                if btn < 0 or btn >= NUM_BUTTONS:
                    continue

                pressed.append(btn)
                idx = len(pressed) - 1
                correct = sequence[idx]
                await ws.send_json(
                    {
                        "type": "press",
                        "button": btn,
                        "index": idx,
                        "correct": btn == correct,
                    }
                )
                if btn != correct:
                    failed = True
                    break

            if failed:
                lives -= 1
                await ws.send_json(
                    {"type": "round_failed", "lives": lives, "sequence": sequence, "cleared": cleared}
                )
                if lives <= 0:
                    break
                continue

            cleared += 1
            await ws.send_json(
                {"type": "round_clear", "cleared": cleared, "lives": lives, "length": length}
            )
            length += p["grow"]

        won = cleared >= p["win_rounds"]
        await ws.send_json(
            {"type": "over", "won": won, "cleared": cleared, "lives": max(0, lives)}
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("pattern session error")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
