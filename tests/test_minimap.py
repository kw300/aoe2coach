"""Small tests for minimap marker classification."""

from __future__ import annotations

from aoe2coach.minimap import _classify_object


def test_minimap_object_classification():
    assert _classify_object(None) is None
    assert _classify_object("Town Center") == "town_center"
    assert _classify_object("Gold Mine") == "gold"
    assert _classify_object("Stone Mine") == "stone"
    assert _classify_object("Forage Bush") == "berries"
    assert _classify_object("Sheep") == "herdable"
    assert _classify_object("Wild Boar") == "hunt"
    assert _classify_object("Relic") == "relic"
    assert _classify_object("House") is None
