"""aoe2coach — an AI coach for Age of Empires II: Definitive Edition replays.

Public API (the stable surface other code and the MCP server build on):

    from aoe2coach import parse_replay, build_metrics
    from aoe2coach.replays import find_replays, resolve_replay

The four pipeline layers live in dedicated modules:
    parse    → raw .aoe2record into structured objects
    metrics  → deterministic coaching features (no model call)
    coach    → the configured model turns metrics + benchmarks into advice
    report   → render advice as markdown
"""

from __future__ import annotations

from .metrics import ReplayMetrics, build_metrics
from .parse import ParsedReplay, parse_replay

__version__ = "0.1.0"

__all__ = [
    "ParsedReplay",
    "ReplayMetrics",
    "build_metrics",
    "parse_replay",
    "__version__",
]
