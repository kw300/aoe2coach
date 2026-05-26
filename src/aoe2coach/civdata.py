"""Resolve numeric IDs from replays into human-readable names.

Names come from bundled JSON tables under ``aoe2coach/data/`` (regenerate with
``aoe2coach update-data`` — see scripts/update_data.py). They're sourced from full
mgz's authoritative, version-stamped reference dataset, so they stay current with new
patches/DLCs. If the tables are missing (e.g. a partial checkout), we fall back to a
small hardcoded civ table and graceful ``"#id"`` labels rather than crashing.
"""

from __future__ import annotations

import json
from functools import cache

# Fallback civ table (community DE ordering) used only if bundled data is unavailable.
_FALLBACK_CIVS: dict[int, str] = {
    1: "Britons",
    2: "Franks",
    3: "Goths",
    4: "Teutons",
    5: "Japanese",
    6: "Chinese",
    7: "Byzantines",
    8: "Persians",
    9: "Saracens",
    10: "Turks",
    11: "Vikings",
    12: "Mongols",
    13: "Celts",
    14: "Spanish",
    15: "Aztecs",
    16: "Mayans",
    17: "Huns",
    18: "Koreans",
    19: "Italians",
    20: "Hindustanis",
    21: "Incas",
    22: "Magyars",
    23: "Slavs",
    24: "Portuguese",
    25: "Ethiopians",
    26: "Malians",
    27: "Berbers",
    28: "Khmer",
    29: "Malay",
    30: "Burmese",
    31: "Vietnamese",
    32: "Bulgarians",
    33: "Tatars",
    34: "Cumans",
    35: "Lithuanians",
    36: "Burgundians",
    37: "Sicilians",
    38: "Poles",
    39: "Bohemians",
    40: "Dravidians",
    41: "Bengalis",
    42: "Gurjaras",
    43: "Romans",
    44: "Armenians",
    45: "Georgians",
}


@cache
def _table(name: str) -> dict:
    """Load a bundled JSON table by filename stem, or {} if unavailable."""
    try:
        from importlib import resources

        path = resources.files("aoe2coach.data").joinpath(f"{name}.json")
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return {}


def _lookup(table: str, id_: int | None, prefix: str) -> str:
    if id_ is None:
        return "Unknown"
    val = _table(table).get(str(id_))
    return val if val else f"{prefix} {id_}"


def civ_name(civ_id: int | None) -> str:
    if civ_id is None:
        return "Unknown"
    table = _table("civilizations")
    if table:
        return table.get(str(civ_id), f"Civ {civ_id}")
    return _FALLBACK_CIVS.get(civ_id, f"Civ {civ_id}")


def map_name(map_id: int | None) -> str:
    return _lookup("maps", map_id, "Map")


def object_name(object_id: int | None) -> str:
    """Name a unit or building by its genie object id (used for build orders)."""
    return _lookup("objects", object_id, "Building")


def tech_name(tech_id: int | None) -> str:
    return _lookup("technologies", tech_id, "Tech")


def terrain_table() -> dict:
    """Return {terrain_id: {name, colors{up,level,down}}} for the minimap renderer."""
    return _table("terrain")


def techtree_table() -> dict:
    """Return {civilization: {Building, Unit, Tech}} from bundled aoe2techtree data."""
    return _table("civ_techtrees")


def manifest() -> dict:
    return _table("manifest")
