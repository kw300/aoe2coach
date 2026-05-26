"""Tests for ELO benchmarking — parsing is tested offline; a live test is optional."""

from __future__ import annotations

import pytest

from aoe2coach.elo import _parse_stats, fetch_ratings, tier_for_rating


def test_tier_bands():
    assert tier_for_rating(None) is None
    assert tier_for_rating(500) == "beginner"
    assert tier_for_rating(900) == "lower-intermediate"
    assert tier_for_rating(1200) == "intermediate"
    assert tier_for_rating(1500) == "advanced"
    assert tier_for_rating(1800) == "expert"


def test_parse_stats_attributes_ratings_to_profiles():
    data = {
        "statGroups": [
            {"id": 100, "members": [{"profile_id": 1234567, "alias": "ExamplePlayer"}]},
        ],
        "leaderboardStats": [
            {"statgroup_id": 100, "leaderboard_id": 3, "rating": 669, "wins": 9, "losses": 25},
            {"statgroup_id": 100, "leaderboard_id": 13, "rating": 904, "wins": 0, "losses": 2},
        ],
    }
    out = _parse_stats(data, [1234567])
    rec = out[1234567]
    assert rec["alias"] == "ExamplePlayer"
    assert rec["rm_1v1_rating"] == 669
    assert rec["tier"] == "beginner"
    assert rec["ratings"]["1v1 Empire Wars"]["rating"] == 904


def test_fetch_ratings_offline_safe(monkeypatch):
    # Force the network call to fail; we must degrade to {} not raise.
    import aoe2coach.elo as elo

    def boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(elo.urllib.request, "urlopen", boom)
    assert fetch_ratings([123]) == {}


@pytest.mark.skip(reason="live network; unskip + use any public profile_id to verify")
def test_live_api():
    # Swap in any public AoE2 profile_id to verify against the real Relic API.
    public_profile_id = 199325
    out = fetch_ratings([public_profile_id])
    assert out and out[public_profile_id]["alias"]
