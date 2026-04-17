from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReactionRushParams:
    initial_window_ms: float
    min_window_ms: float
    decay_per_hit: float  # multiply window after each success (< 1 = harder)
    lives: int
    win_score: int


def reaction_params(difficulty: str) -> ReactionRushParams:
    d = (difficulty or "medium").lower()
    if d == "easy":
        return ReactionRushParams(1400, 550, 0.94, 5, 10)
    if d == "hard":
        return ReactionRushParams(850, 280, 0.88, 2, 15)
    return ReactionRushParams(1100, 350, 0.91, 3, 12)
