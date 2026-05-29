"""Layer 3 — turn deterministic metrics into coaching advice with a model.

This is the only module that calls a model provider. It supports:

- ``anthropic`` — native Anthropic SDK with prompt caching, adaptive thinking, and
  effort controls.
- ``openai`` — OpenAI-compatible chat completions, including OpenAI, OpenRouter, and
  local servers via ``OPENAI_BASE_URL``.

Shared conventions:

- Key handling lives in :mod:`aoe2coach.config` (env-only, fail-fast). The SDK's
  clients can read keys themselves, but we validate first so the error is friendly.
- **Prompt caching:** on the Anthropic path, the system prompt + benchmark reference
  are a large, stable prefix sent as cached system blocks. The per-replay metrics
  JSON — which differs every call — goes in the user turn, after the cache
  breakpoint.
- **Model selection:** configured with ``AOE2COACH_MODEL``; lightweight habit
  detection can use a separate ``AOE2COACH_DETECT_MODEL``.
- **Streaming:** optional, for live output in the terminal.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from importlib import resources

import anthropic

from .benchmarks import BENCHMARKS_MARKDOWN
from .config import PROVIDER_DEFAULTS, Config, load_config
from .contextpack import build_context_pack, format_context_pack
from .metrics import ReplayMetrics


@dataclass
class CoachResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int

    @property
    def cost_note(self) -> str:
        cached = "cache hit" if self.cache_read_tokens else "cache miss (first run)"
        return (
            f"{self.model} · in {self.input_tokens} / out {self.output_tokens} tokens "
            f"· {cached} ({self.cache_read_tokens} cached)"
        )


def _prompt(name: str) -> str:
    return resources.files("aoe2coach.prompts").joinpath(name).read_text("utf-8")


def _build_system_blocks(system_file: str = "system.md") -> list[dict]:
    """System prompt + benchmarks as cached blocks (the stable, reusable prefix)."""
    return [
        {"type": "text", "text": _prompt(system_file)},
        {
            "type": "text",
            "text": BENCHMARKS_MARKDOWN,
            # Cache through the end of the benchmarks — everything before the
            # volatile per-request JSON in the user turn.
            "cache_control": {"type": "ephemeral"},
        },
    ]


def _user_content(metrics: ReplayMetrics, focus_player: str | None, elo: dict | None) -> str:
    # Sort keys for a deterministic payload (also good caching hygiene generally).
    payload = json.dumps(metrics.to_dict(), sort_keys=True, indent=2, default=str)
    focus = (
        f"Focus your coaching on the player named '{focus_player}'.\n\n"
        if focus_player
        else "Coach the player(s) as described in your instructions.\n\n"
    )
    elo_block = ""
    if elo:
        elo_json = json.dumps(elo, sort_keys=True, indent=2, default=str)
        elo_block = (
            "\n\nReal ladder ratings from the ranked API (benchmark against the "
            f"player's actual ELO bracket, not a guess):\n```json\n{elo_json}\n```"
        )
    context_block = format_context_pack(build_context_pack(metrics))
    return (
        f"{focus}Here are the parsed metrics for one replay:\n\n```json\n{payload}\n```"
        f"{elo_block}{context_block}"
    )


def coach_replay(
    metrics: ReplayMetrics,
    *,
    config: Config | None = None,
    focus_player: str | None = None,
    elo: dict | None = None,
    stream: bool = False,
    on_text: Callable[[str], None] | None = None,
) -> CoachResult:
    """Send metrics to the configured model and return coaching advice.

    Args:
        metrics: the deterministic features for one replay.
        config: resolved config; loaded from the environment if omitted.
        focus_player: optionally coach just this player by name.
        elo: optional real ladder ratings by profile_id (see :mod:`aoe2coach.elo`).
        stream: stream tokens as they arrive (calls ``on_text`` per chunk).
        on_text: callback for streamed chunks (e.g. print to stdout).

    Raises:
        anthropic.AuthenticationError: the API key is invalid.
        anthropic.RateLimitError / APIStatusError: surfaced to the caller.
    """
    config = config or load_config(require_key=True)
    return _run(
        _build_system_blocks("system.md"),
        _user_content(metrics, focus_player, elo),
        config=config,
        stream=stream,
        on_text=on_text,
    )


def coach_trends(
    summary,
    *,
    config: Config | None = None,
    stream: bool = False,
    on_text: Callable[[str], None] | None = None,
) -> CoachResult:
    """Send a multi-game :class:`~aoe2coach.trends.TrendSummary` to the configured
    model for recurring-weakness coaching."""
    config = config or load_config(require_key=True)
    payload = json.dumps(summary.to_dict(), sort_keys=True, indent=2, default=str)
    user = (
        f"Here is a player's recent multi-game history. Identify recurring habits and "
        f"give a focused practice plan.\n\n```json\n{payload}\n```"
    )
    return _run(
        _build_system_blocks("trends_system.md"),
        user,
        config=config,
        stream=stream,
        on_text=on_text,
    )


def _habit_detection_payload(metrics: ReplayMetrics) -> dict:
    """Compact replay facts for the lightweight habit detector.

    Deliberately omits deterministic ``improvement_profile`` / ``action_plan`` so
    the model is judging from replay facts rather than rephrasing our thresholds.
    """
    return {
        "replay": {
            "map_name": metrics.map_name,
            "duration_s": metrics.duration_s,
            "recorded_at": metrics.recorded_at,
            "backend": metrics.backend,
            "rated": metrics.rated,
            "matchup_context": metrics.matchup_context,
        },
        "players": [
            {
                "name": p.name,
                "civilization": p.civilization,
                "result": p.result,
                "feudal_time_s": p.feudal_time_s,
                "castle_time_s": p.castle_time_s,
                "imperial_time_s": p.imperial_time_s,
                "build_order_comparison": p.build_order_comparison,
                "villagers_queued": p.villagers_queued,
                "idle_tc_gaps": p.idle_tc_gaps,
                "estimated_idle_tc_s": p.estimated_idle_tc_s,
                "units_trained": p.units_trained,
                "techs": p.techs,
                "key_tech_status": p.key_tech_status,
                "eapm": p.eapm,
                "peak_resources": p.peak_resources,
                "high_float_s": p.high_float_s,
                "biggest_loss": p.biggest_loss,
                "objects_lost_total": p.objects_lost_total,
            }
            for p in metrics.players
        ],
        "battles": metrics.battles,
        "timeline": metrics.timeline,
    }


def _detection_config(config: Config) -> Config:
    detect_model = os.environ.get("AOE2COACH_DETECT_MODEL", "").strip()
    if not detect_model:
        if config.provider == "anthropic":
            detect_model = PROVIDER_DEFAULTS["anthropic"]["detect_model"]
        elif config.provider == "openai" and not config.base_url:
            detect_model = PROVIDER_DEFAULTS["openai"]["detect_model"]
        else:
            detect_model = config.model
    return replace(
        config,
        model=detect_model,
        effort="",
        max_tokens=min(config.max_tokens, 1200),
    )


def _json_from_text(text: str):
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return json.loads(stripped)


def detect_habits(
    metrics: ReplayMetrics,
    *,
    config: Config | None = None,
    focus_player: str | None = None,
) -> dict:
    """Use a cheaper model to propose nuanced practice-focus candidates."""
    config = _detection_config(config or load_config(require_key=True))
    payload = json.dumps(_habit_detection_payload(metrics), sort_keys=True, indent=2, default=str)
    focus = f"\nFocus player: {focus_player}\n" if focus_player else ""
    system = (
        "You are an Age of Empires II practice-plan assistant. Identify candidate "
        "habits a player might pin for deliberate practice, using only the replay "
        "facts provided. Be nuanced: prefer recurring decision patterns over raw "
        "threshold labels. Return ONLY valid JSON with this shape: "
        '{"habits":[{"label":"short habit name","player":"name or both",'
        '"detail":"one sentence with evidence","priority":"high|medium|low"}]}. '
        "Produce 3 to 6 habits. Do not invent facts."
    )
    user = f"{focus}Replay facts:\n```json\n{payload}\n```"
    result = _run(
        [{"type": "text", "text": system}],
        user,
        config=config,
        stream=False,
        on_text=None,
    )
    parsed = _json_from_text(result.text)
    habits = parsed.get("habits", []) if isinstance(parsed, dict) else parsed
    clean = []
    for item in habits if isinstance(habits, list) else []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        detail = str(item.get("detail", "")).strip()
        if not label:
            continue
        clean.append(
            {
                "label": label[:80],
                "player": str(item.get("player", "")).strip()[:80],
                "detail": detail[:240],
                "priority": str(item.get("priority", "medium")).strip().lower()[:12] or "medium",
            }
        )
    return {"habits": clean[:6], "model": result.model, "cost_note": result.cost_note}


def _run(
    system_blocks: list[dict],
    user_text: str,
    *,
    config: Config,
    stream: bool,
    on_text: Callable[[str], None] | None,
) -> CoachResult:
    """Single-shot helper (one user message)."""
    return _run_messages(
        system_blocks,
        [{"role": "user", "content": user_text}],
        config=config,
        stream=stream,
        on_text=on_text,
    )


def _run_messages(
    system_blocks: list[dict],
    messages: list[dict],
    *,
    config: Config,
    stream: bool,
    on_text: Callable[[str], None] | None,
) -> CoachResult:
    """Execute one request for a full message list, dispatching by provider."""
    if config.provider == "openai":
        return _run_openai(system_blocks, messages, config, stream, on_text)
    return _run_anthropic(system_blocks, messages, config, stream, on_text)


def _run_anthropic(system_blocks, messages, config, stream, on_text) -> CoachResult:
    """Native Anthropic path — prompt caching + adaptive thinking + effort."""
    client = anthropic.Anthropic(api_key=config.api_key)
    request = dict(
        model=config.model,
        max_tokens=config.max_tokens,
        system=system_blocks,
        messages=messages,
    )
    if config.effort and _anthropic_uses_adaptive_effort(config.model):
        request["thinking"] = {"type": "adaptive"}
        request["output_config"] = {"effort": config.effort}

    if stream:
        with client.messages.stream(**request) as s:
            for chunk in s.text_stream:
                if on_text:
                    on_text(chunk)
            message = s.get_final_message()
    else:
        message = client.messages.create(**request)

    text = "".join(b.text for b in message.content if b.type == "text")
    usage = message.usage
    return CoachResult(
        text=text,
        model=message.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
    )


def _run_openai(system_blocks, messages, config, stream, on_text) -> CoachResult:
    """OpenAI-compatible path — works with OpenAI, OpenRouter, or a local server via
    ``OPENAI_BASE_URL``. Hosted OpenAI gets reasoning effort; custom endpoints stay
    plain because support varies."""
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            'The openai provider needs the openai package:  pip install -e ".[openai]"'
        ) from exc

    client = OpenAI(api_key=config.api_key, base_url=config.base_url)
    # OpenAI takes one system string + the conversation turns.
    system_text = "\n\n".join(b["text"] for b in system_blocks)
    oa_messages = [{"role": "system", "content": system_text}, *messages]
    request = {"model": config.model, "messages": oa_messages}
    if not config.base_url and config.effort:
        request["reasoning_effort"] = config.effort

    if stream:
        text_parts: list[str] = []
        resp = client.chat.completions.create(**request, stream=True)
        for chunk in resp:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                text_parts.append(delta)
                if on_text:
                    on_text(delta)
        return CoachResult("".join(text_parts), config.model, 0, 0, 0, 0)

    resp = client.chat.completions.create(**request)
    text = resp.choices[0].message.content or ""
    usage = getattr(resp, "usage", None)
    return CoachResult(
        text=text,
        model=getattr(resp, "model", config.model),
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )


def _anthropic_uses_adaptive_effort(model: str) -> bool:
    """Haiku is used as a cheap extraction pass; effort is for analysis-tier models."""
    return "haiku" not in model.lower()


def build_opening_message(
    metrics: ReplayMetrics,
    *,
    focus_player: str | None = None,
    elo: dict | None = None,
    trends=None,
) -> str:
    """The first user turn of a coaching chat: the game's metrics (+ ELO + civ context),
    plus an optional multi-game trends block so follow-ups about habits have context."""
    msg = _user_content(metrics, focus_player, elo)
    if trends is not None:
        tj = json.dumps(trends.to_dict(), sort_keys=True, indent=2, default=str)
        msg += (
            "\n\nFor questions about recurring habits, here is the player's recent "
            f"multi-game history:\n```json\n{tj}\n```"
        )
    return msg


class CoachChat:
    """An interactive, multi-turn coaching session over the API.

    The system prompt + benchmarks are the cached prefix; the conversation accumulates
    in ``messages``. Drive it from a REPL or a web UI: call :meth:`send` with the opening
    message (from :func:`build_opening_message`), then with each follow-up.
    """

    def __init__(self, *, config: Config | None = None, system_file: str = "system.md"):
        self.config = config or load_config(require_key=True)
        self.system_blocks = _build_system_blocks(system_file)
        self.messages: list[dict] = []

    def send(
        self,
        user_text: str,
        *,
        stream: bool = False,
        on_text: Callable[[str], None] | None = None,
    ) -> CoachResult:
        self.messages.append({"role": "user", "content": user_text})
        result = _run_messages(
            self.system_blocks, self.messages, config=self.config, stream=stream, on_text=on_text
        )
        self.messages.append({"role": "assistant", "content": result.text})
        return result
