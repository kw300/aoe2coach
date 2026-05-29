"""Unit tests for the deterministic metrics layer, using synthetic ParsedReplay
objects (no binary fixtures, so no third-party replay PII in the repo).

Integration parsing against a real (compatible) replay lives in
test_parse_integration.py, which downloads a fixture on demand.
"""

from __future__ import annotations

from aoe2coach.civdata import civ_name, map_name
from aoe2coach.metrics import build_metrics
from aoe2coach.parse import ParsedReplay, PlayerReplay


def _player(number, name, civ_id, **kw):
    return PlayerReplay(
        number=number,
        name=name,
        civ_id=civ_id,
        civilization=civ_name(civ_id),
        profile_id=kw.get("profile_id", 1000 + number),
        color_id=kw.get("color_id", number - 1),
        team_id=kw.get("team_id", 1),
        age_up_ms=kw.get("age_up_ms", {}),
        age_research_ms=kw.get("age_research_ms", {}),
        build_actions=kw.get("build_actions", 0),
        total_actions=kw.get("total_actions", 0),
        resigned_at_ms=kw.get("resigned_at_ms"),
        winner=kw.get("winner"),
        eapm=kw.get("eapm"),
        build_order=kw.get("build_order", []),
        building_counts=kw.get("building_counts", {}),
        villager_queue_ms=kw.get("villager_queue_ms", []),
        units_trained=kw.get("units_trained", {}),
        research_names=kw.get("research_names", []),
        timeseries=kw.get("timeseries", []),
    )


def _replay(players, *, backend="full", duration_ms=2_400_000, map_name="Arena"):
    return ParsedReplay(
        path="synthetic.aoe2record",
        backend=backend,
        game_version="VER 66.6",
        build=999999,
        map_name=map_name,
        map_id=29,
        map_size="Tiny",
        diplomacy="1v1",
        duration_ms=duration_ms,
        rated=False,
        speed=1.0,
        population_limit=200,
        players=players,
        body_complete=True,
    )


def test_civ_and_map_names():
    assert civ_name(43) == "Romans"
    assert civ_name(9999) == "Civ 9999"
    assert map_name(None) == "Unknown"


def test_gaia_excluded_from_humans():
    parsed = _replay([_player(0, "Gaia", None, color_id=-1), _player(1, "Alice", 43)])
    assert [p.name for p in build_metrics(parsed).players] == ["Alice"]


def test_age_durations_and_apm():
    alice = _player(
        1,
        "Alice",
        43,
        age_up_ms={"feudal": 600_000, "castle": 900_000, "imperial": 1_800_000},
        total_actions=600,
    )
    p = build_metrics(_replay([alice], duration_ms=1_200_000)).players[0]
    assert p.feudal_time_s == 600
    assert p.feudal_to_castle_s == 300
    assert p.castle_to_imperial_s == 900
    assert p.command_actions_per_min == 30.0


def test_result_from_winner_flag_full_backend():
    winner = _player(1, "W", 43, winner=True)
    loser = _player(2, "L", 10, winner=False)
    by = {p.name: p for p in build_metrics(_replay([winner, loser])).players}
    assert by["W"].result == "won" and by["L"].result == "lost"


def test_result_from_resignation_fast_backend():
    a = _player(1, "A", 1)
    b = _player(2, "B", 2, resigned_at_ms=1_500_000)
    by = {p.name: p for p in build_metrics(_replay([a, b], backend="fast")).players}
    assert by["A"].result == "won" and by["B"].result == "lost"


def test_idle_tc_gap_detection():
    # Villagers every 25s, but a 90s gap starting at 4:00 (240s) — idle TC.
    times = list(range(0, 240_000, 25_000)) + [330_000, 355_000, 380_000]
    p = _player(1, "Alice", 43, villager_queue_ms=times)
    m = build_metrics(_replay([p])).players[0]
    assert m.villagers_queued == len(times)
    assert m.villagers_16m == 3 + len(times)
    assert m.longest_idle_gap_s >= 60
    # The 90s gap (~65s over the 25s ideal) should register as idle time.
    assert m.estimated_idle_tc_s >= 60
    assert any(g["gap_s"] >= 60 for g in m.idle_tc_gaps)


def test_batched_villager_queues_do_not_count_as_idle_tc():
    p = _player(1, "Alice", 43, villager_queue_ms=[0, 0, 0, 0, 100_000])
    m = build_metrics(_replay([p])).players[0]
    assert m.idle_tc_gaps == []
    assert m.estimated_idle_tc_s == 0


def test_idle_tc_ignores_age_research_time():
    p = _player(
        1,
        "Alice",
        43,
        age_up_ms={"feudal": 700_000},
        age_research_ms={"feudal": 570_000},
        villager_queue_ms=[560_000, 715_000],
    )
    m = build_metrics(_replay([p])).players[0]
    assert m.idle_tc_gaps == []
    assert m.estimated_idle_tc_s == 0


def test_build_order_labels_and_units():
    p = _player(
        1,
        "Alice",
        43,
        age_up_ms={"feudal": 650_000},
        build_order=[(2000, "House"), (590_000, "Barracks"), (760_000, "Stable")],
        units_trained={"Knight": 10, "Monk": 2},
        research_names=["Feudal Age", "Loom", "Wheelbarrow", "Castle Age", "Loom"],
    )
    m = build_metrics(_replay([p])).players[0]
    assert m.build_order == ["House@0:02", "Barracks@9:50", "Stable@12:40"]
    assert m.units_trained["Knight"] == 10
    assert m.techs == ["Loom", "Wheelbarrow"]  # age-ups filtered, order-preserving, deduped
    assert m.techs_researched == 2  # distinct count, not duplicate click events
    assert m.opening == "Unclear opening"
    assert m.opening_confidence == "low"
    feudal = next(c for c in m.build_order_comparison if c["checkpoint"] == "Feudal")
    assert feudal["status"] == "early"


def test_key_tech_status_joins_researched_and_civ_availability():
    malay = _player(
        1,
        "Malay",
        29,
        research_names=["Husbandry", "Blast Furnace", "Scale Barding Armor"],
    )
    khmer = _player(2, "Khmer", 28, research_names=["Bloodlines"])
    metrics = build_metrics(_replay([malay, khmer]))
    by_name = {
        p.name: {row["tech"]: row["status"] for row in p.key_tech_status} for p in metrics.players
    }

    assert by_name["Malay"]["Husbandry"] == "researched"
    assert by_name["Malay"]["Blast Furnace"] == "researched"
    assert by_name["Malay"]["Bloodlines"] == "not_available"
    assert by_name["Malay"]["Cavalier"] == "available_not_researched"
    assert by_name["Malay"]["Chain Barding Armor"] == "not_available"
    assert by_name["Malay"]["Plate Barding Armor"] == "not_available"
    assert by_name["Khmer"]["Bloodlines"] == "researched"
    assert by_name["Khmer"]["Husbandry"] == "available_not_researched"
    assert by_name["Khmer"]["Plate Barding Armor"] == "available_not_researched"
    assert by_name["Khmer"]["Elite Battle Elephant"] == "available_not_researched"


def test_key_tech_status_empty_for_fast_backend():
    p = _player(1, "Alice", 28, research_names=["Bloodlines"])
    m = build_metrics(_replay([p], backend="fast")).players[0]
    assert m.key_tech_status == []


def test_action_plan_and_timeline_from_deterministic_profile():
    # Idle TC plus a late/missing military check should produce a concrete practice plan.
    times = list(range(0, 200_000, 25_000)) + [320_000, 345_000]
    p = _player(
        1,
        "Alice",
        43,
        age_up_ms={"feudal": 780_000},
        villager_queue_ms=times,
        build_order=[(2_000, "House")],
    )
    m = build_metrics(_replay([p], duration_ms=1_500_000))
    alice = m.players[0]

    assert alice.opening == "Unclear opening"
    assert alice.improvement_profile[0]["area"] == "Town Center uptime"
    assert alice.action_plan[0]["focus"] == "Town Center uptime"
    assert any(e["type"] == "idle_tc" for e in m.timeline)
    assert m.matchup_context["map_style"] == "closed"


def test_matchup_context_for_open_1v1():
    a = _player(
        1,
        "Franks",
        8,
        age_up_ms={"feudal": 640_000},
        build_order=[(580_000, "Barracks"), (730_000, "Stable")],
    )
    b = _player(
        2,
        "Britons",
        2,
        age_up_ms={"feudal": 650_000},
        build_order=[(600_000, "Barracks"), (740_000, "Archery Range")],
    )
    m = build_metrics(_replay([a, b], duration_ms=1_800_000, map_name="Arabia"))
    assert m.players[0].opening == "Unclear opening"
    assert m.players[1].opening == "Unclear opening"
    assert m.matchup_context["map_style"] == "open"


def test_battle_timeline_and_resource_float():
    # Two players. At ~5:00 a fight: A loses 30 objects, B loses 5 (A loses the trade).
    # (ms, total_objects, total_resources)
    a_ts = [(0, 50, 200), (300_000, 120, 1800), (310_000, 90, 1900), (600_000, 130, 800)]
    b_ts = [(0, 50, 200), (300_000, 110, 300), (310_000, 105, 300), (600_000, 160, 300)]
    a = _player(1, "A", 43, timeseries=a_ts)
    b = _player(2, "B", 10, timeseries=b_ts)
    m = build_metrics(_replay([a, b]))

    assert m.battles, "expected at least one detected engagement"
    fight = m.battles[0]
    assert fight["losses"]["A"] == 30 and fight["losses"]["B"] == 5
    assert fight["trade_winner"] == "B"  # B lost far fewer

    by = {p.name: p for p in m.players}
    assert by["A"].peak_objects == 130
    assert by["A"].biggest_loss == {"at": "5:10", "count": 30}
    # A floated >1500 across the 5:00→5:10 sample (~10s); B never floated.
    assert by["A"].high_float_s and by["A"].high_float_s > 0
    assert by["B"].high_float_s == 0


def test_metrics_dict_is_json_ready():
    d = build_metrics(_replay([_player(1, "Solo", 43)])).to_dict()
    assert d["map_name"] == "Arena"
    assert d["backend"] == "full"
    assert d["duration_label"] == "40:00"
