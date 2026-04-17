from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MinigameInfo:
    id: str
    title: str
    description: str
    notes: str


def list_minigames() -> list[MinigameInfo]:
    """
    Registry of planned minigames. Implementations can be added incrementally
    (HTTP/WebSocket handlers + front-end modules per game).
    """
    return [
        MinigameInfo(
            id="rps",
            title="Rock Paper Scissors",
            description="Three arcade buttons map to rock, paper, scissors vs the Gamemaster.",
            notes="Play at /minigames/rps — best of 3; map 3 physical buttons (one per choice).",
        ),
        MinigameInfo(
            id="simon",
            title="Simon Says",
            description="Repeat an increasing sequence of lit buttons.",
            notes="Play at /minigames/simon — easy = slow pace, extreme = faster + longer + strict.",
        ),
        MinigameInfo(
            id="reaction",
            title="Reaction Rush",
            description="Live: random lit button; shrinking reaction window (Web UI + WS).",
            notes="Play at /minigames/reaction-rush — map GPIO to button ids 0–14.",
        ),
        MinigameInfo(
            id="pattern",
            title="Pattern Match",
            description="Memorize a color sequence, then recreate it in order on the grid.",
            notes="Play at /minigames/pattern — each round the sequence grows by one.",
        ),
        MinigameInfo(
            id="whack_a_mole",
            title="Whack-a-Mole",
            description="Live: safe vs trap moles; clear safes before time (Web UI + WS).",
            notes="Play at /minigames/whack-mole — traps cost a life and end the round.",
        ),
    ]
