"""Multi-game trend analysis — read a player's habits across many replays.

A single game shows a snapshot; trends show whether you *keep* idling your Town
Center, whether your Feudal time is improving, which civs/maps you struggle on. This
module aggregates per-game :class:`~aoe2coach.metrics.ReplayMetrics` for one focus
player into a :class:`TrendSummary`, which :func:`aoe2coach.coach.coach_trends` then
turns into recurring-weakness coaching.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field

from .metrics import ReplayMetrics

# A game counts as "idle TC" if estimated idle exceeds this (seconds).
_IDLE_FLAG_S = 60


@dataclass
class GameRow:
    map_name: str
    civilization: str
    result: str
    feudal_s: int | None
    castle_s: int | None
    imperial_s: int | None
    villagers: int | None
    idle_tc_s: int | None
    eapm: int | None


@dataclass
class TrendSummary:
    player: str
    n_games: int
    backend: str
    wins: int
    losses: int
    win_rate: float | None
    avg_feudal_s: int | None
    avg_castle_s: int | None
    avg_idle_tc_s: int | None
    avg_villagers: int | None
    feudal_direction: str  # "improving" | "worsening" | "flat" | "n/a"
    idle_tc_game_fraction: float | None  # share of games with notable idle TC
    civ_counts: dict[str, int]
    map_counts: dict[str, int]
    games: list[GameRow] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _focus_player_name(metrics_list: list[ReplayMetrics], override: str | None) -> str | None:
    if override:
        return override
    names = Counter(p.name for m in metrics_list for p in m.players)
    return names.most_common(1)[0][0] if names else None


def _avg(values: list[int]) -> int | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals)) if vals else None


def _direction(values: list[int | None]) -> str:
    """Earlier vs. later average of a 'lower is better' metric (e.g. Feudal time)."""
    vals = [v for v in values if v is not None]
    if len(vals) < 4:
        return "n/a"
    mid = len(vals) // 2
    first, second = _avg(vals[:mid]), _avg(vals[mid:])
    if first is None or second is None:
        return "n/a"
    delta = second - first
    if abs(delta) < 15:  # within 15s — noise
        return "flat"
    return "improving" if delta < 0 else "worsening"


def aggregate(metrics_list: list[ReplayMetrics], focus_player: str | None = None) -> TrendSummary:
    """Aggregate per-game metrics for one focus player (chronological order assumed)."""
    name = _focus_player_name(metrics_list, focus_player)
    rows: list[GameRow] = []
    backend = metrics_list[0].backend if metrics_list else "unknown"
    for m in metrics_list:
        p = next((pl for pl in m.players if pl.name == name), None)
        if p is None:
            continue
        rows.append(
            GameRow(
                map_name=m.map_name,
                civilization=p.civilization,
                result=p.result,
                feudal_s=p.feudal_time_s,
                castle_s=p.castle_time_s,
                imperial_s=p.imperial_time_s,
                villagers=(p.villagers_queued or None),
                idle_tc_s=p.estimated_idle_tc_s,
                eapm=p.eapm,
            )
        )

    wins = sum(1 for r in rows if r.result == "won")
    losses = sum(1 for r in rows if r.result == "lost")
    decided = wins + losses
    idle_vals = [r.idle_tc_s for r in rows if r.idle_tc_s is not None]
    idle_flagged = sum(1 for v in idle_vals if v > _IDLE_FLAG_S)

    return TrendSummary(
        player=name or "unknown",
        n_games=len(rows),
        backend=backend,
        wins=wins,
        losses=losses,
        win_rate=round(wins / decided, 2) if decided else None,
        avg_feudal_s=_avg([r.feudal_s for r in rows]),
        avg_castle_s=_avg([r.castle_s for r in rows]),
        avg_idle_tc_s=_avg(idle_vals),
        avg_villagers=_avg([r.villagers for r in rows]),
        feudal_direction=_direction([r.feudal_s for r in rows]),
        idle_tc_game_fraction=(round(idle_flagged / len(idle_vals), 2) if idle_vals else None),
        civ_counts=dict(Counter(r.civilization for r in rows).most_common()),
        map_counts=dict(Counter(r.map_name for r in rows).most_common()),
        games=rows,
    )
