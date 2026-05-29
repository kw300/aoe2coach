"""MCP server — the "hybrid", no-API-key path.

Exposes the deterministic core (parse → metrics → trends, plus the coaching
framing) over the Model Context Protocol, so an MCP-compatible client can read your
replays and coach you using *its own* model. No ``ANTHROPIC_API_KEY`` lives here;
the client supplies the intelligence.

It reuses the exact same library functions as the CLI — only the transport differs.

What it offers:
- **Tools** (the model calls these to fetch data):
  ``list_replays``, ``replay_metrics``, ``replay_trends``.
- **Prompts** (you invoke these; they pre-frame a well-structured coaching request,
  injecting the same expert system prompt + benchmarks the API path uses):
  ``coach``, ``coach_trends``.

Run it:
    pip install -e ".[full,mcp]"      # or ".[fast,mcp]" for current-patch games
    claude mcp add aoe2coach -- python -m aoe2coach.mcp_server
    #   …or add it to Claude Desktop's MCP config and just chat.
"""

from __future__ import annotations

import json
from importlib import resources

from . import build_metrics, parse_replay
from .benchmarks import BENCHMARKS_MARKDOWN
from .contextpack import build_context_pack, format_context_pack
from .replays import find_replays, resolve_replay
from .trends import aggregate

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        'The MCP server needs the optional "mcp" dependency:  pip install -e ".[mcp]"'
    ) from exc

mcp = FastMCP("aoe2coach")


def _coaching_instructions(system_file: str) -> str:
    return resources.files("aoe2coach.prompts").joinpath(system_file).read_text("utf-8")


def _metrics_for(replay: str):
    """Parse + build metrics for one replay (path or 'latest')."""
    return build_metrics(parse_replay(resolve_replay(replay)))


def _recent_metrics(last: int):
    """Parse the most recent ``last`` replays, oldest-first, skipping any the
    installed backend can't read."""
    paths = list(reversed(find_replays()[:last]))
    out = []
    for p in paths:
        try:
            out.append(build_metrics(parse_replay(p)))
        except Exception:  # noqa: BLE001 - skip a replay the backend can't parse
            continue
    return out


# --------------------------------------------------------------------------- #
# Tools — the model calls these to pull data
# --------------------------------------------------------------------------- #


@mcp.tool()
def list_replays() -> str:
    """List the AoE2 DE replay files discovered on this machine, newest first."""
    return json.dumps([str(p) for p in find_replays()], indent=2)


@mcp.tool()
def replay_metrics(replay: str = "latest") -> str:
    """Parse one replay and return its coaching metrics (plus civ context) as JSON.

    Args:
        replay: path to a .aoe2record file, or "latest" for the most recent.
    """
    try:
        metrics = _metrics_for(replay)
    except Exception as exc:  # noqa: BLE001 - return a friendly message, don't crash the tool
        return json.dumps({"error": str(exc)})
    payload = metrics.to_dict()
    payload["civ_context"] = build_context_pack(metrics)
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


@mcp.tool()
def replay_trends(last: int = 10, player: str | None = None) -> str:
    """Aggregate your recent games into recurring-habit trends.

    Args:
        last: how many recent replays to include (default 10).
        player: focus player name (default: the most frequent across the games).
    """
    metrics_list = _recent_metrics(last)
    if not metrics_list:
        return json.dumps({"error": "No parseable replays found."})
    return json.dumps(aggregate(metrics_list, player).to_dict(), indent=2, default=str)


# --------------------------------------------------------------------------- #
# Prompts — you invoke these; they hand the client model the full framing
# --------------------------------------------------------------------------- #


@mcp.prompt()
def coach(replay: str = "latest", player: str | None = None) -> str:
    """A ready-to-send coaching request for one replay, framed with the expert
    system prompt + benchmarks (so the client's model coaches like aoe2coach does)."""
    try:
        metrics = _metrics_for(replay)
    except Exception as exc:  # noqa: BLE001
        return f"Could not parse replay '{replay}': {exc}"
    metrics_json = json.dumps(metrics.to_dict(), sort_keys=True, indent=2, default=str)
    context = format_context_pack(build_context_pack(metrics))
    focus = f"\nFocus on the player named '{player}'.\n" if player else ""
    return (
        f"{_coaching_instructions('system.md')}\n\n"
        f"# Benchmarks\n\n{BENCHMARKS_MARKDOWN}\n\n"
        f"# This game's metrics\n\n```json\n{metrics_json}\n```{context}\n"
        f"{focus}\nCoach this game following the instructions above. After the report, "
        f"invite me to ask follow-up questions."
    )


@mcp.prompt()
def coach_trends(last: int = 10, player: str | None = None) -> str:
    """A ready-to-send multi-game request, framed with the trends system prompt +
    benchmarks, to surface recurring habits across your recent games."""
    metrics_list = _recent_metrics(last)
    if not metrics_list:
        return "No parseable replays found to analyze for trends."
    summary_json = json.dumps(
        aggregate(metrics_list, player).to_dict(), sort_keys=True, indent=2, default=str
    )
    return (
        f"{_coaching_instructions('trends_system.md')}\n\n"
        f"# Benchmarks\n\n{BENCHMARKS_MARKDOWN}\n\n"
        f"# Recent games (aggregated)\n\n```json\n{summary_json}\n```\n\n"
        f"Identify my recurring habits and give a focused practice plan."
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
