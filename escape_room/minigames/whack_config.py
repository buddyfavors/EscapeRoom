from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WhackMoleParams:
    round_window_ms: float
    rounds: int
    lives: int
    min_moles: int
    max_moles: int
    trap_chance: float  # per lit mole (non-safe)


def whack_params(difficulty: str) -> WhackMoleParams:
    d = (difficulty or "medium").lower()
    if d == "easy":
        return WhackMoleParams(3200, 6, 4, 2, 3, 0.15)
    if d == "hard":
        return WhackMoleParams(2200, 10, 2, 3, 5, 0.45)
    return WhackMoleParams(2800, 8, 3, 2, 4, 0.3)
