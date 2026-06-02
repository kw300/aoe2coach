"""AoE2 player color helpers.

Replay parsers expose raw color ids as zero-based DE palette slots in the full
backend (0 blue, 1 red, ...). The full backend also exposes a human-readable
color label; prefer that label when present because it is clearer than raw ids.
"""

from __future__ import annotations

_PALETTE = [
    ("blue", "#3c6eff", (60, 110, 255)),
    ("red", "#e63232", (230, 50, 50)),
    ("green", "#3cc83c", (60, 200, 60)),
    ("yellow", "#f0e63c", (240, 230, 60)),
    ("cyan", "#28c8e6", (40, 200, 230)),
    ("purple", "#f082e6", (240, 130, 230)),
    ("gray", "#828282", (130, 130, 130)),
    ("orange", "#f58c28", (245, 140, 40)),
]

_ALIASES = {
    "blue": "blue",
    "red": "red",
    "green": "green",
    "yellow": "yellow",
    "cyan": "cyan",
    "teal": "cyan",
    "purple": "purple",
    "grey": "gray",
    "gray": "gray",
    "orange": "orange",
}


def _index(color_id: int | None) -> int | None:
    if color_id is None or color_id < 0:
        return None
    return color_id % len(_PALETTE)


def color_name_from_label(label: str | None) -> str | None:
    if not label:
        return None
    return _ALIASES.get(str(label).strip().lower())


def color_hex_from_name(name: str | None) -> str | None:
    normalized = color_name_from_label(name)
    if normalized is None:
        return None
    for color, hexv, _rgb in _PALETTE:
        if color == normalized:
            return hexv
    return None


def color_rgb_from_name(name: str | None) -> tuple[int, int, int] | None:
    normalized = color_name_from_label(name)
    if normalized is None:
        return None
    for color, _hexv, rgb in _PALETTE:
        if color == normalized:
            return rgb
    return None


def color_name(color_id: int | None) -> str | None:
    idx = _index(color_id)
    return None if idx is None else _PALETTE[idx][0]


def color_hex(color_id: int | None) -> str | None:
    idx = _index(color_id)
    return None if idx is None else _PALETTE[idx][1]


def color_rgb(color_id: int | None) -> tuple[int, int, int] | None:
    idx = _index(color_id)
    return None if idx is None else _PALETTE[idx][2]
