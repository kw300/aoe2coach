"""Configuration, model provider selection, and API-key handling.

aoe2coach is **bring-your-own-model**. Two provider backends:

- ``anthropic`` (default) — the native Anthropic SDK; best results on Claude Opus 4.7,
  with prompt caching and adaptive thinking.
- ``openai`` — any OpenAI-compatible endpoint. Set ``OPENAI_BASE_URL`` to point at
  OpenAI, OpenRouter (→ GPT, Claude, Gemini, …), or a local server (Ollama/LM Studio).

Best-practice key handling, enforced here:
- Keys come from environment variables only — never hard-coded, never defaulted.
- A local ``.env`` (gitignored) is loaded for convenience.
- Missing/invalid config fails fast with a clear, actionable message — and the key is
  never logged or echoed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_PROVIDER = "anthropic"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-7"
DEFAULT_EFFORT = "medium"  # snappier coaching; set AOE2COACH_EFFORT=high for max depth
DEFAULT_MAX_TOKENS = 8000


class ConfigError(RuntimeError):
    """Raised for missing/invalid configuration. The CLI prints this cleanly."""


@dataclass
class Config:
    provider: str  # "anthropic" | "openai"
    api_key: str
    model: str
    effort: str
    max_tokens: int
    base_url: str | None = None


def load_config(require_key: bool = True) -> Config:
    """Resolve configuration from the environment (and a local .env if present).

    Args:
        require_key: if True (default), raise :class:`ConfigError` when the selected
            provider's key (or required model) is missing. Pass False for code paths
            that don't call a model (e.g. ``aoe2coach metrics``).
    """
    load_dotenv()  # no-op without a .env; never overrides real env vars

    provider = os.environ.get("AOE2COACH_PROVIDER", DEFAULT_PROVIDER).strip().lower()
    model = (os.environ.get("AOE2COACH_MODEL") or "").strip() or None
    effort = os.environ.get("AOE2COACH_EFFORT", DEFAULT_EFFORT)
    max_tokens = int(os.environ.get("AOE2COACH_MAX_TOKENS", DEFAULT_MAX_TOKENS))

    if provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        model = model or DEFAULT_ANTHROPIC_MODEL
        base_url = None
        key_hint = (
            "ANTHROPIC_API_KEY is not set.\n"
            "  1. Get a key: https://console.anthropic.com/settings/keys\n"
            "  2. cp env.example .env  and paste your key in, OR export ANTHROPIC_API_KEY=...\n"
            "Or switch providers: AOE2COACH_PROVIDER=openai (see env.example)."
        )
    elif provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        base_url = (os.environ.get("OPENAI_BASE_URL") or "").strip() or None
        if require_key and not model:
            raise ConfigError(
                "AOE2COACH_PROVIDER=openai requires AOE2COACH_MODEL (e.g. a GPT model, "
                "or an OpenRouter id like 'anthropic/claude-opus-4-7'). See env.example."
            )
        key_hint = (
            "OPENAI_API_KEY is not set (required for AOE2COACH_PROVIDER=openai).\n"
            "Set OPENAI_API_KEY, and optionally OPENAI_BASE_URL for OpenRouter / a local "
            "server. See env.example."
        )
    else:
        raise ConfigError(f"Unknown AOE2COACH_PROVIDER '{provider}'. Use 'anthropic' or 'openai'.")

    if require_key and not api_key:
        raise ConfigError(key_hint)

    return Config(
        provider=provider,
        api_key=api_key,
        model=model or "",
        effort=effort,
        max_tokens=max_tokens,
        base_url=base_url,
    )
