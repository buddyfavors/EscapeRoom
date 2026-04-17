from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from typing import Any

from fastapi import WebSocket

from escape_room.minigames.button_grid import color_name
from escape_room.minigames.whack_config import whack_params

logger = logging.getLogger(__name__)


async def run_whack_mole_session(ws: WebSocket) -> None:
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
    p = whack_params(diff)
    rng = random.Random()
    score = 0
    lives = p.lives

    await ws.send_json(
        {
            "type": "started",
            "difficulty": diff,
            "lives": lives,
            "rounds": p.rounds,
            "round_window_ms": p.round_window_ms,
        }
    )

    try:
        for round_i in range(p.rounds):
            if lives <= 0:
                break

            n_moles = rng.randint(p.min_moles, p.max_moles)
            indices = rng.sample(range(15), n_moles)
            moles: list[dict[str, Any]] = []
            for i in indices:
                trap = rng.random() < p.trap_chance
                moles.append({"i": i, "trap": trap, "color": color_name(i)})

            if not any(not m["trap"] for m in moles):
                moles[0]["trap"] = False

            safes = {m["i"] for m in moles if not m["trap"]}
            traps = {m["i"] for m in moles if m["trap"]}
            lit = {m["i"] for m in moles}
            cleared: set[int] = set()

            deadline = time.monotonic() + p.round_window_ms / 1000.0
            await ws.send_json(
                {
                    "type": "round",
                    "index": round_i + 1,
                    "moles": moles,
                    "score": score,
                    "lives": lives,
                }
            )

            round_failed = False
            while time.monotonic() < deadline and lives > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    msg = await asyncio.wait_for(
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
                    btn = int(msg.get("button"))
                except (TypeError, ValueError):
                    continue

                if btn not in lit:
                    continue

                if btn in traps:
                    lives -= 1
                    await ws.send_json(
                        {
                            "type": "trap_hit",
                            "button": btn,
                            "lives": lives,
                            "score": score,
                            "message": "Trap! The Gamemaster loves greed.",
                        }
                    )
                    round_failed = True
                    break

                if btn in safes:
                    cleared.add(btn)
                    await ws.send_json(
                        {
                            "type": "safe_hit",
                            "button": btn,
                            "cleared": sorted(cleared),
                            "need": sorted(safes),
                            "score": score,
                            "lives": lives,
                        }
                    )
                    if cleared >= safes:
                        score += 1
                        await ws.send_json({"type": "round_clear", "score": score, "lives": lives})
                        round_failed = False
                        break

            if lives <= 0:
                break

            if round_failed:
                continue

            if cleared < safes:
                lives -= 1
                await ws.send_json(
                    {
                        "type": "round_timeout",
                        "message": "Safe moles left standing — the Gamemaster scores.",
                        "score": score,
                        "lives": lives,
                        "missed": sorted(safes - cleared),
                    }
                )

        need = max(1, math.ceil(p.rounds * 0.55))
        won = lives > 0 and score >= need
        await ws.send_json(
            {
                "type": "over",
                "won": won,
                "score": score,
                "lives": max(0, lives),
                "cleared_needed": need,
            }
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("whack mole session error")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
