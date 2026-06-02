"""Tests for local per-replay civ context packs."""

from __future__ import annotations

from aoe2coach.coach import _user_content
from aoe2coach.contextpack import build_context_pack, format_context_pack
from aoe2coach.metrics import build_metrics
from aoe2coach.parse import ParsedReplay, PlayerReplay


def _replay(*players: PlayerReplay) -> ParsedReplay:
    return ParsedReplay(
        path="synthetic.aoe2record",
        backend="full",
        game_version="v66",
        build=1,
        map_name="Arabia",
        map_id=9,
        map_size="Tiny",
        diplomacy="1v1",
        duration_ms=1_800_000,
        rated=True,
        speed=1.0,
        population_limit=200,
        players=list(players),
        body_complete=True,
    )


def _player(number: int, name: str, civ_id: int, civilization: str) -> PlayerReplay:
    return PlayerReplay(
        number=number,
        name=name,
        civ_id=civ_id,
        civilization=civilization,
        profile_id=1000 + number,
        color_id=number - 1,
        color_name=None,
        team_id=number,
    )


def test_context_pack_resolves_techtree_names_and_bonus_blurb():
    metrics = build_metrics(
        _replay(
            _player(1, "A", 28, "Khmer"),
            _player(2, "B", 16, "Maya"),
        )
    )

    pack = build_context_pack(metrics)
    by_name = {c["name"]: c for c in pack["civilizations"]}

    assert set(by_name) == {"Khmer", "Maya"}
    assert by_name["Khmer"]["techtree_key"] == "Khmer"
    assert "houses are not needed" in by_name["Khmer"]["bonus_blurb"]
    assert "House" in by_name["Khmer"]["available_buildings"]
    assert by_name["Maya"]["techtree_key"] == "Mayans"
    assert "archers are cheaper" in by_name["Maya"]["bonus_blurb"]


def test_context_pack_is_injected_into_user_turn_only():
    metrics = build_metrics(_replay(_player(1, "A", 28, "Khmer")))
    content = _user_content(metrics, focus_player=None, elo=None)

    assert "Local civ context for this replay" in content
    assert "civ_techtrees.json" in content
    assert "houses are not needed" in content


def test_empty_context_pack_formats_to_empty_string():
    assert format_context_pack({"source": "x", "civilizations": []}) == ""
