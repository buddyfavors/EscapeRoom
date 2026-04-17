from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from fastapi import WebSocket

from escape_room.minigames.button_grid import BUTTON_COLORS, color_index

logger = logging.getLogger(__name__)

NUM_COLORS = len(BUTTON_COLORS)


def _difficulty_params(diff: str) -> dict[str, Any]:
    diff = (diff or "medium").lower()
    if diff == "easy":
        return {"start_len": 2, "win_rounds": 8, "lives": 2, "step_ms": 650, "input_timeout_s": 5.0}
    if diff == "hard":
        return {"start_len": 3, "win_rounds": 12, "lives": 1, "step_ms": 350, "input_timeout_s": 2.5}
    return {"start_len": 2, "win_rounds": 10, "lives": 1, "step_ms": 500, "input_timeout_s": 3.5}


async def run_simon_session(ws: WebSocket) -> None:
    first = await ws.receive_json()
    if first.get("action") != "start":
        await ws.send_json({"type": "error", "message": 'Send {"action":"start"} first.'})
        return

    diff = str(first.get("difficulty", "medium")).lower()
    p = _difficulty_params(diff)
    rng = random.Random()
    lives = p["lives"]
    cleared = 0
    sequence: list[int] = []
    for _ in range(p["start_len"]):
        sequence.append(rng.randrange(NUM_COLORS))

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
            await ws.send_json(
                {
                    "type": "play_sequence",
                    "sequence": list(sequence),
                    "step_ms": p["step_ms"],
                    "round": cleared + 1,
                    "lives": lives,
                }
            )

            pressed: list[int] = []
            failed = False
            while len(pressed) < len(sequence):
                try:
                    msg = await asyncio.wait_for(
                        ws.receive_json(), timeout=p["input_timeout_s"]
                    )
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
                    col = color_index(btn)
                except (TypeError, ValueError):
                    if "column" in msg:
                        col = int(msg["column"])
                    else:
                        continue

                pressed.append(col)
                idx = len(pressed) - 1
                correct = sequence[idx]
                await ws.send_json(
                    {
                        "type": "press",
                        "column": col,
                        "index": idx,
                        "correct": col == correct,
                    }
                )
                if col != correct:
                    failed = True
                    break

            if failed:
                lives -= 1
                await ws.send_json(
                    {"type": "round_failed", "lives": lives, "cleared": cleared, "sequence": sequence}
                )
                if lives <= 0:
                    break
                continue

            cleared += 1
            await ws.send_json(
                {"type": "round_clear", "cleared": cleared, "lives": lives, "length": len(sequence)}
            )
            sequence.append(rng.randrange(NUM_COLORS))

        won = cleared >= p["win_rounds"]
        await ws.send_json(
            {"type": "over", "won": won, "cleared": cleared, "lives": max(0, lives)}
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("simon session error")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
