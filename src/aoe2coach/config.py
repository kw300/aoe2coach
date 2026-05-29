"""Configuration, model provider selection, and API-key handling.

aoe2coach is **bring-your-own-model**. Two first-class hosted provider paths:

- ``anthropic`` (default) — the native Anthropic SDK, with prompt caching and adaptive
  thinking.
- ``openai`` — the OpenAI SDK. Without ``OPENAI_BASE_URL`` this uses OpenAI's hosted API
  and supplies smart defaults; with ``OPENAI_BASE_URL`` it can target OpenRouter or local
  servers, but the model id must match that endpoint.

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
DEFAULT_MAX_TOKENS = 8000
PROVIDER_DEFAULTS = {
    "anthropic": {
        "analysis_model": "claude-opus-4-8",
        "detect_model": "claude-haiku-4-5",
        "effort": "high",
        "efforts": {"low", "medium", "high", "xhigh", "max"},
    },
    "openai": {
        "analysis_model": "gpt-5.5",
        "detect_model": "gpt-5.4-mini",
        "effort": "high",
        "efforts": {"none", "low", "medium", "high", "xhigh"},
    },
}


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

    provider = os.environ.get("AOE2COACH_PROVIDER", "").strip().lower()
    if not provider:
        if os.environ.get("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif os.environ.get("OPENAI_API_KEY"):
            provider = "openai"
        else:
            provider = DEFAULT_PROVIDER
    model = (os.environ.get("AOE2COACH_MODEL") or "").strip() or None
    effort_override = (os.environ.get("AOE2COACH_EFFORT") or "").strip().lower() or None
    max_tokens = int(os.environ.get("AOE2COACH_MAX_TOKENS", DEFAULT_MAX_TOKENS))

    if provider == "anthropic":
        defaults = PROVIDER_DEFAULTS["anthropic"]
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        model = model or defaults["analysis_model"]
        base_url = None
        effort = effort_override or defaults["effort"]
        if effort not in defaults["efforts"]:
            raise ConfigError(
                "AOE2COACH_EFFORT for Anthropic must be one of: low, medium, high, xhigh, max."
            )
        key_hint = (
            "ANTHROPIC_API_KEY is not set.\n"
            "  1. Get a key: https://console.anthropic.com/settings/keys\n"
            "  2. cp env.example .env  and paste your key in, OR export ANTHROPIC_API_KEY=...\n"
            "Or switch providers: AOE2COACH_PROVIDER=openai (see env.example)."
        )
    elif provider == "openai":
        defaults = PROVIDER_DEFAULTS["openai"]
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        base_url = (os.environ.get("OPENAI_BASE_URL") or "").strip() or None
        effort = effort_override or defaults["effort"]
        if effort not in defaults["efforts"]:
            raise ConfigError(
                "AOE2COACH_EFFORT for OpenAI must be one of: none, low, medium, high, xhigh."
            )
        if not model and not base_url:
            model = defaults["analysis_model"]
        if require_key and not model:
            raise ConfigError(
                "AOE2COACH_PROVIDER=openai with OPENAI_BASE_URL requires AOE2COACH_MODEL "
                "(use the model id served by that endpoint). See env.example."
            )
        key_hint = (
            "OPENAI_API_KEY is not set (required for AOE2COACH_PROVIDER=openai).\n"
            "Get a key: https://platform.openai.com/api-keys\n"
            "Set OPENAI_API_KEY, and optionally OPENAI_BASE_URL + AOE2COACH_MODEL for "
            "OpenRouter / a local server. See env.example."
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
