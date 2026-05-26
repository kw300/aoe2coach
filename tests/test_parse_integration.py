"""Integration test: parse a real, compatible replay end-to-end.

Downloads a small DE fixture from the aoc-mgz test corpus on demand (cached under
the pytest tmp cache) so we don't commit a multi-MB binary with third-party player
names. Skips cleanly when offline or when the fast backend is installed (the full
fixture requires the full backend).
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import pytest

from aoe2coach import build_metrics, parse_replay
from aoe2coach.parse import _detect_backend

# A real 1v1 DE replay (v66) from the aoc-mgz test corpus — the newest version full
# mgz supports, with standard villager production. Parseable by the full backend.
_FIXTURE_URL = (
    "https://raw.githubusercontent.com/happyleavesaoc/aoc-mgz/master/tests/recs/de-66.6.aoe2record"
)


@pytest.fixture(scope="session")
def compatible_replay(tmp_path_factory) -> Path:
    if _detect_backend() != "full":
        pytest.skip("compatible fixture needs the full mgz backend")
    dest = tmp_path_factory.mktemp("recs") / "de-62.0.aoe2record"
    try:
        data = urllib.request.urlopen(
            urllib.request.Request(_FIXTURE_URL, headers={"User-Agent": "aoe2coach-tests"}),
            timeout=60,
        ).read()
    except Exception as exc:  # offline / network blocked
        pytest.skip(f"could not download fixture: {exc}")
    dest.write_bytes(data)
    return dest


def test_full_backend_extracts_rich_metrics(compatible_replay):
    parsed = parse_replay(compatible_replay)
    assert parsed.backend == "full"
    assert parsed.duration_ms > 0
    assert parsed.humans, "expected human players"

    metrics = build_metrics(parsed)
    # Rich signals the full backend should populate.
    assert any(p.build_order for p in metrics.players), "expected named build orders"
    assert any(p.villagers_queued > 0 for p in metrics.players), "expected villager production"
    assert all(p.result in ("won", "lost", "unknown") for p in metrics.players)
