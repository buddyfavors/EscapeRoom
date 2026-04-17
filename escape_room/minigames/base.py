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
            description="Three arcade buttons map to rock, paper, scissors vs the house.",
            notes="Map 3 physical buttons (one per choice); optional LED feedback per color.",
        ),
        MinigameInfo(
            id="simon",
            title="Simon Says",
            description="Repeat an increasing sequence of lit buttons.",
            notes="easy: slower pace + shorter sequences; extreme: faster + longer + stricter timing.",
        ),
        MinigameInfo(
            id="hangman",
            title="Hangman",
            description="Guess a word letter-by-letter; great tie-in to 5-letter combo locks.",
            notes="Use colored button groups as letter buckets or a soft keyboard on the monitor.",
        ),
        MinigameInfo(
            id="reaction",
            title="Reaction Rush",
            description="Live: random lit button; shrinking reaction window (Web UI + WS).",
            notes="Play at /minigames/reaction-rush — map GPIO to button ids 0–14.",
        ),
        MinigameInfo(
            id="pattern_match",
            title="Pattern Match",
            description="Show a short color sequence; players recreate it with colored buttons.",
            notes="Pairs with Green/Blue/White/Yellow/Red ×3 layout; GM/AI can inject decoy flashes.",
        ),
        MinigameInfo(
            id="whack_a_mole",
            title="Whack-a-Mole",
            description="Live: safe vs trap moles; clear safes before time (Web UI + WS).",
            notes="Play at /minigames/whack-mole — traps cost a life and end the round.",
        ),
    ]
