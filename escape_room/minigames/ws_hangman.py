from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Sequence
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Fallback 5-letter word list used when the letter5 code pool is empty.
FALLBACK_WORDS: tuple[str, ...] = (
    "BRICK", "CRANE", "DRIVE", "FLAME", "GHOST",
    "JOKER", "KNIFE", "LATCH", "MAGIC", "NIGHT",
    "OCEAN", "PIXEL", "QUIET", "RADAR", "STORM",
    "TIGER", "VAULT", "WATCH", "ZEBRA", "PLANT",
)


def _difficulty_params(diff: str) -> dict[str, Any]:
    diff = (diff or "medium").lower()
    if diff == "easy":
        return {"max_wrong": 7, "turn_timeout_s": 25.0}
    if diff == "hard":
        return {"max_wrong": 5, "turn_timeout_s": 10.0}
    return {"max_wrong": 6, "turn_timeout_s": 18.0}


def _pick_word(rng: random.Random, pool: Sequence[str]) -> str:
    cleaned = [w.strip().upper() for w in pool if w and len(w.strip()) == 5 and w.strip().isalpha()]
    if not cleaned:
        cleaned = list(FALLBACK_WORDS)
    return rng.choice(cleaned)


def _mask(word: str, guessed: set[str]) -> list[str | None]:
    return [ch if ch in guessed else None for ch in word]


async def run_hangman_session(ws: WebSocket, *, word_pool: Sequence[str]) -> None:
    first = await ws.receive_json()
    if first.get("action") != "start":
        await ws.send_json({"type": "error", "message": 'Send {"action":"start"} first.'})
        return

    diff = str(first.get("difficulty", "medium")).lower()
    p = _difficulty_params(diff)
    rng = random.Random()
    word = _pick_word(rng, word_pool)
    max_wrong = p["max_wrong"]
    turn_timeout_s = p["turn_timeout_s"]

    guessed: set[str] = set()
    wrong = 0

    await ws.send_json(
        {
            "type": "started",
            "difficulty": diff,
            "length": len(word),
            "max_wrong": max_wrong,
            "turn_timeout_ms": int(turn_timeout_s * 1000),
            "mask": _mask(word, guessed),
        }
    )

    try:
        while wrong < max_wrong and not all(ch in guessed for ch in word):
            try:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=turn_timeout_s + 0.5)
            except asyncio.TimeoutError:
                wrong += 1
                await ws.send_json(
                    {
                        "type": "timeout",
                        "wrong": wrong,
                        "max_wrong": max_wrong,
                        "mask": _mask(word, guessed),
                    }
                )
                continue

            if msg.get("action") == "ping":
                continue
            if msg.get("action") != "guess":
                continue

            letter = str(msg.get("letter", "")).upper().strip()
            if not letter or len(letter) != 1 or not letter.isalpha():
                await ws.send_json({"type": "error", "message": "Send one letter A-Z."})
                continue
            if letter in guessed:
                await ws.send_json(
                    {
                        "type": "repeat",
                        "letter": letter,
                        "guessed": sorted(guessed),
                        "wrong": wrong,
                        "mask": _mask(word, guessed),
                    }
                )
                continue

            guessed.add(letter)
            hit = letter in word
            if not hit:
                wrong += 1
            await ws.send_json(
                {
                    "type": "result",
                    "letter": letter,
                    "hit": hit,
                    "wrong": wrong,
                    "max_wrong": max_wrong,
                    "guessed": sorted(guessed),
                    "mask": _mask(word, guessed),
                }
            )

        won = all(ch in guessed for ch in word)
        await ws.send_json(
            {"type": "over", "won": won, "word": word, "wrong": wrong, "max_wrong": max_wrong}
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("hangman session error")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
