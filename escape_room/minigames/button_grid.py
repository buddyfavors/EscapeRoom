from __future__ import annotations

"""15 arcade buttons: 5 colors × 3 copies. Index 0–14 = color_index * 3 + slot_in_color."""

# Column order matches physical rig: Green, Blue, White, Yellow, Red (×3 each).
BUTTON_COLORS: tuple[str, ...] = ("Green", "Blue", "White", "Yellow", "Red")
NUM_BUTTONS = 15


def color_index(button_id: int) -> int:
    return max(0, min(NUM_BUTTONS - 1, button_id)) // 3


def color_name(button_id: int) -> str:
    return BUTTON_COLORS[color_index(button_id)]


def slot_in_color(button_id: int) -> int:
    return max(0, min(NUM_BUTTONS - 1, button_id)) % 3
