"""Tests for multi-game trend aggregation (synthetic — no parsing/network)."""

from __future__ import annotations

from aoe2coach.civdata import civ_name
from aoe2coach.metrics import build_metrics
from aoe2coach.parse import ParsedReplay, PlayerReplay
from aoe2coach.trends import aggregate


def _game(feudal_ms, idle_ms_list, result_winner, *, civ=43, opp_civ=10, map_name="Arabia"):
    """Build one ReplayMetrics with focus player 'Me' vs 'Opp'."""
    me = PlayerReplay(
        1,
        "Me",
        civ,
        civ_name(civ),
        1001,
        0,
        1,
        age_up_ms={"feudal": feudal_ms} if feudal_ms else {},
        winner=result_winner,
        villager_queue_ms=idle_ms_list,
    )
    opp = PlayerReplay(
        2,
        "Opp",
        opp_civ,
        civ_name(opp_civ),
        1002,
        1,
        2,
        winner=(not result_winner) if result_winner is not None else None,
    )
    parsed = ParsedReplay(
        path="x",
        backend="full",
        game_version="v66",
        build=1,
        map_name=map_name,
        map_id=9,
        map_size="Tiny",
        diplomacy="1v1",
        duration_ms=2_400_000,
        rated=True,
        speed=1.0,
        population_limit=200,
        players=[me, opp],
        body_complete=True,
    )
    return build_metrics(parsed)


# Villager queues with a big gap → idle TC; without → clean.
_IDLE = list(range(0, 200_000, 25_000)) + [320_000, 345_000]  # ~95s gap
_CLEAN = list(range(0, 400_000, 25_000))


def test_aggregate_win_rate_and_focus_detection():
    games = [
        _game(600_000, _CLEAN, True),
        _game(620_000, _CLEAN, False),
        _game(610_000, _CLEAN, True),
    ]
    s = aggregate(games)  # focus auto-detected
    assert s.player == "Me"
    assert s.n_games == 3
    assert s.wins == 2 and s.losses == 1
    assert s.win_rate == round(2 / 3, 2)


def test_aggregate_idle_fraction_and_averages():
    games = [
        _game(600_000, _IDLE, True),
        _game(600_000, _IDLE, False),
        _game(600_000, _CLEAN, True),
    ]
    s = aggregate(games, focus_player="Me")
    assert s.avg_feudal_s == 600
    # 2 of 3 games have notable idle TC.
    assert s.idle_tc_game_fraction == round(2 / 3, 2)
    assert s.civ_counts.get("Romans") == 3


def test_feudal_direction_improving():
    # Feudal times dropping over 6 games → improving.
    times = [780_000, 760_000, 740_000, 660_000, 640_000, 620_000]
    games = [_game(t, _CLEAN, True) for t in times]
    s = aggregate(games, focus_player="Me")
    assert s.feudal_direction == "improving"


def test_dict_is_json_ready():
    s = aggregate([_game(600_000, _CLEAN, True)], focus_player="Me")
    d = s.to_dict()
    assert d["player"] == "Me" and isinstance(d["games"], list)
