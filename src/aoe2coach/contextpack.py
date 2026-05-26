"""Small per-replay context packs for model coaching.

The cached system prompt stays generic. This module builds a targeted user-turn
payload from local bundled data: just the civilizations in the current replay,
their available tech-tree entries, and a short curated bonus blurb when we have
one. Missing data degrades to an empty pack instead of blocking analysis.
"""

from __future__ import annotations

import json

from . import civdata
from .metrics import ReplayMetrics

_CIV_ALIASES = {
    # mgz.reference uses the in-game singular; aoe2techtree uses the civ label.
    "Maya": "Mayans",
}

# Coaching-oriented one-liners, intentionally separate from generated techtree data.
# This can grow over time without changing the cached base prompt.
_BONUS_BLURBS = {
    "Burgundians": (
        "Economic upgrades are available one age earlier and cost less food; "
        "Cavalier arrives in Castle Age."
    ),
    "Khmer": (
        "No buildings are required to advance ages, houses are not needed for "
        "population, and farmers do not need drop-off buildings."
    ),
    "Maya": (
        "Resources last longer and archers are cheaper; the usual plan often rewards "
        "clean archer production and careful gold use."
    ),
    "Mayans": (
        "Resources last longer and archers are cheaper; the usual plan often rewards "
        "clean archer production and careful gold use."
    ),
    "Sicilians": (
        "Units take reduced bonus damage, Town Centers build faster, and "
        "Donjons/Serjeants can shape early map control."
    ),
    "Turks": (
        "Gunpowder is central: Chemistry is free in Imperial, gold miners work "
        "faster, and light cavalry upgrades are free."
    ),
}


def _norm(name: str) -> str:
    return "".join(ch.lower() for ch in name if ch.isalnum())


def _resolve_civ_key(civ_name: str, table: dict) -> str | None:
    if civ_name in table:
        return civ_name
    alias = _CIV_ALIASES.get(civ_name)
    if alias in table:
        return alias

    wanted = _norm(civ_name)
    for key in table:
        if _norm(key) == wanted:
            return key
    return None


def _named_ids(ids: list[int], resolver) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for raw in ids or []:
        try:
            name = resolver(int(raw))
        except (TypeError, ValueError):
            continue
        if name not in seen:
            seen.add(name)
            names.append(name)
    return sorted(names)


def build_context_pack(metrics: ReplayMetrics, *, max_civs: int = 2) -> dict:
    """Build a compact local-data context pack for the civilizations in one replay."""
    table = civdata.techtree_table()
    if not table:
        return {"source": "local civ_techtrees.json unavailable", "civilizations": []}

    civs: list[dict] = []
    seen: set[str] = set()
    for player in metrics.players:
        civ_name = player.civilization
        if not civ_name or civ_name == "Unknown":
            continue
        key = _resolve_civ_key(civ_name, table)
        dedupe = key or civ_name
        if dedupe in seen:
            continue
        seen.add(dedupe)

        raw = table.get(key or "", {})
        civs.append(
            {
                "name": civ_name,
                "techtree_key": key,
                "bonus_blurb": _BONUS_BLURBS.get(
                    civ_name,
                    _BONUS_BLURBS.get(key or "", "No curated bonus blurb is bundled yet."),
                ),
                "available_buildings": _named_ids(raw.get("Building", []), civdata.object_name),
                "available_units": _named_ids(raw.get("Unit", []), civdata.object_name),
                "available_techs": _named_ids(raw.get("Tech", []), civdata.tech_name),
            }
        )
        if len(civs) >= max_civs:
            break

    return {
        "source": "local bundled civ_techtrees.json plus curated bonus blurbs",
        "civilizations": civs,
    }


def format_context_pack(pack: dict) -> str:
    """Render a context pack as a user-turn block. Returns '' when there is no data."""
    if not pack.get("civilizations"):
        return ""
    payload = json.dumps(pack, sort_keys=True, indent=2, ensure_ascii=False)
    return (
        "\n\nLocal civ context for this replay. Use it for civ-specific coaching, "
        "especially whether build-order choices, unit lines, or tech switches fit "
        "the civilization. The tech-tree lists availability; do not claim a unit or "
        f"tech was used unless it appears in the replay metrics.\n```json\n{payload}\n```"
    )
