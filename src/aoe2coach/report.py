"""Layer 4 — render metrics + coaching advice into a markdown report."""

from __future__ import annotations

import datetime as _dt
import html
import re
from pathlib import Path

from .metrics import ReplayMetrics


def _players_table(metrics: ReplayMetrics) -> str:
    rich = metrics.backend == "full"
    if rich:
        header = (
            "| Player | Civ | Opening | Result | Feudal | Castle | Imperial | Vills | "
            "Idle TC | EAPM |"
        )
        sep = (
            "|--------|-----|---------|--------|--------|--------|----------|-------|"
            "---------|------|"
        )
    else:
        header = "| Player | Civ | Opening | Result | Feudal | Castle | Imperial | Cmd/min |"
        sep = "|--------|-----|---------|--------|--------|--------|----------|---------|"
    rows = [header, sep]
    for p in metrics.players:
        lb = p.labels
        if rich:
            idle = "—" if p.estimated_idle_tc_s is None else f"{p.estimated_idle_tc_s}s"
            vills = p.villagers_queued or "—"
            eapm = p.eapm if p.eapm is not None else "—"
            rows.append(
                f"| {p.name} | {p.civilization} | {p.opening} | {p.result} | "
                f"{lb['feudal']} | {lb['castle']} | {lb['imperial']} | {vills} | "
                f"{idle} | {eapm} |"
            )
        else:
            apm = "—" if p.command_actions_per_min is None else f"{p.command_actions_per_min:g}"
            rows.append(
                f"| {p.name} | {p.civilization} | {p.opening} | {p.result} | "
                f"{lb['feudal']} | {lb['castle']} | {lb['imperial']} | {apm} |"
            )
    return "\n".join(rows)


def _matchup_context(metrics: ReplayMetrics) -> str:
    ctx = metrics.matchup_context or {}
    notes = ctx.get("notes") or []
    if not notes:
        return ""
    lines = [f"**Matchup context** · map style: `{ctx.get('map_style', 'unknown')}`", ""]
    lines.extend(f"- {note}" for note in notes)
    return "\n".join(lines) + "\n"


def _action_plans(metrics: ReplayMetrics) -> str:
    lines = []
    for p in metrics.players:
        if not p.action_plan:
            continue
        lines.append(f"**{p.name}: post-game action plan**")
        for item in p.action_plan[:3]:
            lines.append(
                f"{item['priority']}. **{item['focus']}** — {item['why']}. "
                f"Drill: {item['drill']} Target: {item['target']}"
            )
        lines.append("")
    if not lines:
        return ""
    return "\n".join(lines).rstrip() + "\n"


def _build_comparisons(metrics: ReplayMetrics) -> str:
    blocks = []
    for p in metrics.players:
        rows = [
            c
            for c in p.build_order_comparison
            if c["status"] in {"late", "missing"} or p.opening != "Unclear opening"
        ]
        if not rows:
            continue
        blocks.append(f"**{p.name}: early timing checks**")
        for c in rows[:4]:
            blocks.append(
                f"- {c['checkpoint']}: {c['actual']} vs target {c['target']} ({c['status']})"
            )
        blocks.append("")
    if not blocks:
        return ""
    return "\n".join(blocks).rstrip() + "\n"


def _build_orders(metrics: ReplayMetrics) -> str:
    """A short build-order line per player (full backend only)."""
    lines = []
    for p in metrics.players:
        if p.build_order:
            lines.append(f"- **{p.name}:** " + " → ".join(p.build_order[:10]))
    if not lines:
        return ""
    return "**Build orders**\n\n" + "\n".join(lines) + "\n"


def _replay_timeline(metrics: ReplayMetrics) -> str:
    """A chronological timeline of deterministic replay events."""
    if not metrics.timeline:
        return ""
    lines = ["**Replay timeline**", ""]
    for event in metrics.timeline[:16]:
        lines.append(f"- **{event['at']}** — {event['label']}")
    return "\n".join(lines) + "\n"


def build_report(metrics: ReplayMetrics, coaching: str, model: str) -> str:
    """Compose the full markdown report: facts table + build orders + model coaching."""
    rated = "ranked" if metrics.rated else "unranked"
    map_label = metrics.map_name + (f" ({metrics.map_size})" if metrics.map_size else "")
    date_label = f" · **Date:** {metrics.recorded_at}" if metrics.recorded_at else ""
    incomplete = "" if metrics.body_complete else " _(replay body was truncated)_"
    matchup = _matchup_context(metrics)
    action_plans = _action_plans(metrics)
    comparisons = _build_comparisons(metrics)
    build_orders = _build_orders(metrics)
    timeline = _replay_timeline(metrics)
    mid = "\n".join(s for s in (matchup, action_plans, comparisons, build_orders, timeline) if s)
    mid_section = f"\n{mid}\n---\n" if mid else ""
    return f"""\
# AoE2 Coaching Report

**Map:** {map_label}{date_label} · **Duration:** {metrics.to_dict()["duration_label"]} · \
**{rated}** · build {metrics.build} · parser: `{metrics.backend}`{incomplete}

{_players_table(metrics)}
{mid_section}
{coaching}

---

_Generated by [aoe2coach](https://github.com/kw300/aoe2coach) using {model}. Metrics are \
computed deterministically from the replay; battle events are inferred from \
object-count data (not a tactical replay); coaching is AI-generated — verify against your \
own judgment._
"""


def default_report_path(metrics: ReplayMetrics, out_dir: str | Path = "reports") -> Path:
    """A stable, readable output path derived from the replay + timestamp."""
    out_dir = Path(out_dir)
    stem = Path(metrics.source_file).stem
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in stem).strip()[:60]
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return out_dir / f"{safe or 'replay'}-{ts}.coach.md"


def _markdown_label(value: str) -> str:
    """Keep replay/player labels as text when opened in a Markdown viewer."""
    value = html.escape(" ".join(value.splitlines()), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+!|])", r"\\\1", value)


def build_chat_export(
    *,
    replay_name: str,
    map_name: str,
    duration_label: str,
    players: list[dict],
    focus_player: str | None,
    messages: list[dict],
) -> str:
    """Export the visible transcript, supplied separately from model context.

    Callers provide display labels and visible messages only; this function never
    reads a chat object's internal prompts, metrics, configuration, or API keys.
    """
    roster = ", ".join(
        f"{_markdown_label(p['name'])} ({_markdown_label(p['civilization'])})" for p in players
    )
    lines = [
        "# AoE2 Coaching Conversation",
        "",
        f"**Replay:** {_markdown_label(Path(replay_name).name)}",
        f"**Map:** {_markdown_label(map_name)} · **Duration:** {_markdown_label(duration_label)}",
        f"**Players:** {roster}",
        f"**Coaching focus:** {_markdown_label(focus_player) if focus_player else 'All players'}",
        "",
    ]
    for message in messages:
        role = message["role"]
        if role not in {"user", "assistant", "error"}:
            continue
        heading = {"user": "You", "assistant": "Coach", "error": "Request failed"}[role]
        lines.extend([f"## {heading}", ""])
        if role == "assistant":
            model = _markdown_label(message.get("model") or "unavailable")
            input_tokens = message.get("input_tokens")
            output_tokens = message.get("output_tokens")
            input_label = str(input_tokens) if input_tokens is not None else "unavailable"
            output_label = str(output_tokens) if output_tokens is not None else "unavailable"
            lines.extend([message["text"], ""])
            lines.extend(
                [
                    f"_Model: {model} · Input tokens: {input_label} "
                    f"· Output tokens: {output_label}_",
                    "",
                ]
            )
        else:
            # Browser user/error messages are plain text; quote them so their
            # Markdown syntax does not become report headings or HTML on export.
            lines.extend(
                ["> " + _markdown_label(line) for line in message["text"].splitlines()] + [""]
            )
    return "\n".join(lines).rstrip() + "\n"
