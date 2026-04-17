from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

from fastapi import WebSocket

from escape_room.minigames.button_grid import BUTTON_COLORS, NUM_BUTTONS, color_name
from escape_room.minigames.reaction_config import reaction_params

logger = logging.getLogger(__name__)

GRACE_S = 0.08


async def run_reaction_rush_session(ws: WebSocket) -> None:
    first = await ws.receive_json()
    if first.get("action") != "start":
        await ws.send_json(
            {
                "type": "error",
                "message": 'Send {"action":"start","difficulty":"easy|medium|hard"} first.',
            }
        )
        return

    diff = str(first.get("difficulty", "medium")).lower()
    p = reaction_params(diff)
    rng = random.Random()
    window_ms = p.initial_window_ms
    score = 0
    lives = p.lives

    await ws.send_json(
        {
            "type": "started",
            "difficulty": diff,
            "lives": lives,
            "win_score": p.win_score,
            "colors": list(BUTTON_COLORS),
        }
    )

    try:
        while lives > 0 and score < p.win_score:
            target = rng.randrange(NUM_BUTTONS)
            t0 = time.monotonic()
            window_s = max(p.min_window_ms, window_ms) / 1000.0
            deadline = t0 + window_s + GRACE_S

            await ws.send_json(
                {
                    "type": "go",
                    "target": target,
                    "window_ms": window_s * 1000,
                    "color": color_name(target),
                    "score": score,
                    "lives": lives,
                }
            )

            hit_ok = False
            already_penalized = False
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    msg: dict[str, Any] = await asyncio.wait_for(
                        ws.receive_json(),
                        timeout=min(remaining, 0.12),
                    )
                except asyncio.TimeoutError:
                    continue

                if msg.get("action") == "ping":
                    continue
                if msg.get("action") != "hit":
                    continue

                try:
                    btn_i = int(msg.get("button"))
                except (TypeError, ValueError):
                    continue

                if time.monotonic() - t0 > window_s + GRACE_S:
                    break

                if btn_i == target:
                    hit_ok = True
                    break

                lives -= 1
                already_penalized = True
                await ws.send_json(
                    {
                        "type": "miss",
                        "reason": "wrong_button",
                        "score": score,
                        "lives": lives,
                        "target": target,
                    }
                )
                break

            if hit_ok:
                score += 1
                window_ms = max(p.min_window_ms, window_ms * p.decay_per_hit)
                await ws.send_json({"type": "hit_ok", "score": score, "lives": lives, "window_ms": window_ms})
            elif not already_penalized and lives > 0:
                lives -= 1
                await ws.send_json(
                    {
                        "type": "miss",
                        "reason": "timeout",
                        "score": score,
                        "lives": lives,
                        "target": target,
                    }
                )

        won = score >= p.win_score
        await ws.send_json({"type": "over", "won": won, "score": score, "lives": max(0, lives)})
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("reaction rush session error")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
