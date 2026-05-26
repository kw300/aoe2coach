"""Fetch real ladder ratings by profile_id, so coaching benchmarks against a
player's actual ELO bracket instead of generic tiers.

Source: the official Relic/World's Edge community leaderboard API
(`aoe-api.worldsedgelink.com`). All network access is best-effort — on failure or
offline we return nothing and the coach falls back to map-based tier guidance. The
parsing is split from the fetch so it can be unit-tested without the network.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

_API = "https://aoe-api.worldsedgelink.com/community/leaderboard/getPersonalStat"

# Common age2 DE leaderboard ids → readable names.
LEADERBOARDS = {
    1: "1v1 Deathmatch",
    2: "Team Deathmatch",
    3: "1v1 Random Map",
    4: "Team Random Map",
    13: "1v1 Empire Wars",
    14: "Team Empire Wars",
}

# Approximate 1v1 Random Map ELO bands (the ladder most players track).
_TIERS = [
    (700, "beginner"),
    (1000, "lower-intermediate"),
    (1300, "intermediate"),
    (1600, "advanced"),
]


def tier_for_rating(rating: int | None) -> str | None:
    if rating is None:
        return None
    for ceiling, label in _TIERS:
        if rating < ceiling:
            return label
    return "expert"


def _parse_stats(data: dict, profile_ids: list[int]) -> dict[int, dict]:
    """Turn a getPersonalStat response into {profile_id: {...}}.

    Pure function — no network — so it's unit-testable.
    """
    # Map statGroup id → (profile_id, alias) so we can attribute leaderboard rows.
    group_to_profile: dict[int, tuple[int, str]] = {}
    for grp in data.get("statGroups", []) or []:
        for member in grp.get("members", []) or []:
            pid = member.get("profile_id")
            if pid is not None:
                group_to_profile[grp.get("id")] = (pid, member.get("alias", ""))

    out: dict[int, dict] = {pid: {"alias": None, "ratings": {}} for pid in profile_ids}
    for row in data.get("leaderboardStats", []) or []:
        gid = row.get("statgroup_id") if "statgroup_id" in row else row.get("statGroup_id")
        info = group_to_profile.get(gid)
        if not info:
            continue
        pid, alias = info
        if pid not in out:
            continue
        out[pid]["alias"] = out[pid]["alias"] or alias
        lb_id = row.get("leaderboard_id")
        out[pid]["ratings"][LEADERBOARDS.get(lb_id, f"leaderboard {lb_id}")] = {
            "rating": row.get("rating"),
            "wins": row.get("wins"),
            "losses": row.get("losses"),
            "leaderboard_id": lb_id,
        }

    # Convenience: surface the 1v1 Random Map rating + tier.
    for rec in out.values():
        rm = rec["ratings"].get("1v1 Random Map")
        rec["rm_1v1_rating"] = rm["rating"] if rm else None
        rec["tier"] = tier_for_rating(rec["rm_1v1_rating"])
    return out


def fetch_ratings(profile_ids: list[int], *, timeout: float = 15.0) -> dict[int, dict]:
    """Best-effort fetch of ladder ratings for the given profile ids. Returns {} on
    any network/parse failure (offline-safe)."""
    ids = [pid for pid in profile_ids if pid]
    if not ids:
        return {}
    url = f"{_API}?title=age2&profile_ids=[{','.join(str(p) for p in ids)}]"
    try:
        raw = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "aoe2coach"}), timeout=timeout
        ).read()
        return _parse_stats(json.loads(raw), ids)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return {}
