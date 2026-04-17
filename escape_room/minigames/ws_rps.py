from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

CHOICES = ("rock", "paper", "scissors")

# Pause after each reveal so players can read the board before the next round.
INTER_ROUND_PAUSE_S = 2.6
BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}


def _difficulty_params(diff: str) -> dict[str, Any]:
    diff = (diff or "medium").lower()
    if diff == "easy":
        return {"win_target": 2, "turn_timeout_s": 15.0, "bias": 0.0}
    if diff == "hard":
        return {"win_target": 3, "turn_timeout_s": 6.0, "bias": 0.45}
    return {"win_target": 2, "turn_timeout_s": 10.0, "bias": 0.2}


def _pick_gm_move(rng: random.Random, history: list[str], bias: float) -> str:
    """
    Gamemaster move: random, with optional bias that counters the player's
    most-used move. Higher bias = more predictive (harder).
    """
    if not history or bias <= 0 or rng.random() > bias:
        return rng.choice(CHOICES)
    counts: dict[str, int] = {c: 0 for c in CHOICES}
    for m in history:
        counts[m] = counts.get(m, 0) + 1
    favorite = max(counts, key=lambda k: counts[k])
    counter = {v: k for k, v in BEATS.items()}[favorite]
    return counter


def _resolve(player: str, gm: str) -> str:
    if player == gm:
        return "tie"
    return "win" if BEATS[player] == gm else "lose"


async def run_rps_session(ws: WebSocket) -> None:
    first = await ws.receive_json()
    if first.get("action") != "start":
        await ws.send_json({"type": "error", "message": 'Send {"action":"start"} first.'})
        return

    diff = str(first.get("difficulty", "medium")).lower()
    params = _difficulty_params(diff)
    win_target = params["win_target"]
    timeout_s = params["turn_timeout_s"]
    bias = params["bias"]
    rng = random.Random()

    score = {"player": 0, "gm": 0}
    history: list[str] = []
    round_i = 0

    await ws.send_json(
        {
            "type": "started",
            "difficulty": diff,
            "win_target": win_target,
            "turn_timeout_ms": int(timeout_s * 1000),
            "choices": list(CHOICES),
        }
    )

    try:
        while score["player"] < win_target and score["gm"] < win_target:
            round_i += 1
            await ws.send_json(
                {
                    "type": "round",
                    "index": round_i,
                    "score": score,
                    "turn_timeout_ms": int(timeout_s * 1000),
                }
            )

            try:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=timeout_s + 0.5)
            except asyncio.TimeoutError:
                score["gm"] += 1
                await ws.send_json(
                    {
                        "type": "reveal",
                        "player": None,
                        "gm": rng.choice(CHOICES),
                        "outcome": "lose",
                        "reason": "timeout",
                        "score": score,
                    }
                )
                await asyncio.sleep(INTER_ROUND_PAUSE_S)
                continue

            if msg.get("action") != "play":
                continue
            player = str(msg.get("choice", "")).lower()
            if player not in CHOICES:
                await ws.send_json({"type": "error", "message": "Invalid choice."})
                round_i -= 1
                continue

            gm = _pick_gm_move(rng, history, bias)
            history.append(player)
            outcome = _resolve(player, gm)
            if outcome == "win":
                score["player"] += 1
            elif outcome == "lose":
                score["gm"] += 1

            await ws.send_json(
                {
                    "type": "reveal",
                    "player": player,
                    "gm": gm,
                    "outcome": outcome,
                    "score": score,
                }
            )
            await asyncio.sleep(INTER_ROUND_PAUSE_S)

        won = score["player"] >= win_target
        await ws.send_json({"type": "over", "won": won, "score": score, "rounds": round_i})
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("rps session error")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
