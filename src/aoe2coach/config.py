"""Environment-only model connections with optional overrides for each coaching task.

Hosted Anthropic and OpenAI have provider-specific defaults. Custom endpoints need
endpoint-specific model IDs. Existing ``.env`` files keep working; task overrides
use ``AOE2COACH_<TASK>_<OPTION>``. Keys are never logged or included in config reprs.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from dotenv import load_dotenv

DEFAULT_PROVIDER = "anthropic"
DEFAULT_MAX_TOKENS = 8000
TASKS = ("analysis", "chat", "trends", "detect")
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
    """Raised for missing/invalid configuration. Messages never include API keys."""


@dataclass
class Config:
    provider: str
    api_key: str = field(repr=False)
    model: str
    effort: str
    max_tokens: int
    base_url: str | None = field(default=None, repr=False)
    thinking: str = "adaptive"
    api_key_env: str = ""


def _env(name: str) -> str | None:
    return os.environ.get(name, "").strip() or None


def load_config(require_key: bool = True, *, task: str | None = None) -> Config:
    """Resolve a default or task-specific model connection.

    Unset/blank task options inherit the default. A provider change uses the new
    provider's model, endpoint, key, and effort defaults. Detection keeps its cheap
    model and 1200-token cap unless explicitly overridden. ``require_key=False``
    allows a missing key/model for offline diagnostics; malformed options still fail.
    """
    load_dotenv()  # never overrides real environment variables
    if task is not None and task not in TASKS:
        raise ConfigError("Unknown coaching task. Use analysis, chat, trends, or detect.")
    prefix = f"AOE2COACH_{task.upper()}_" if task else "AOE2COACH_"
    default_provider = _env("AOE2COACH_PROVIDER")
    if not default_provider:
        if _env("ANTHROPIC_API_KEY"):
            default_provider = "anthropic"
        elif _env("OPENAI_API_KEY"):
            default_provider = "openai"
        else:
            default_provider = DEFAULT_PROVIDER
    default_provider = default_provider.lower()
    provider = (_env(prefix + "PROVIDER") or default_provider).lower()
    if provider not in PROVIDER_DEFAULTS:
        raise ConfigError(f"{prefix}PROVIDER must be 'anthropic' or 'openai'.")
    defaults = PROVIDER_DEFAULTS[provider]
    same_provider = provider == default_provider

    def option(name: str, *, connection: bool = False) -> str | None:
        value = _env(prefix + name)
        if value is None and (not connection or same_provider):
            value = _env("AOE2COACH_" + name)
        return value

    native_prefix = provider.upper()
    base_url = option("BASE_URL", connection=True) or _env(f"{native_prefix}_BASE_URL")
    if base_url:
        try:
            url = urlsplit(base_url)
            valid_url = (
                url.scheme in {"http", "https"}
                and url.hostname
                and not url.username
                and not url.password
                and not url.query
                and not url.fragment
                and not any(character.isspace() for character in base_url)
            )
            _ = url.port  # validate a supplied port without including its value in errors
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ConfigError(
                f"{prefix}BASE_URL must be an HTTP(S) endpoint "
                "without credentials, query, or fragment."
            )

    model = option("MODEL", connection=True)
    if task == "detect" and not _env(prefix + "MODEL"):
        # Hosted providers have a lightweight extraction model. Endpoint model IDs
        # are private to the endpoint, so reuse its configured model by default.
        model = model if base_url else defaults["detect_model"]
    if not model and (provider == "anthropic" or not base_url):
        model = defaults["analysis_model"]
    if require_key and not model:
        raise ConfigError(
            f"{prefix}MODEL is required for a custom openai endpoint "
            "(use the model ID served by that endpoint). See env.example."
        )

    effort_override = (
        _env(prefix + "EFFORT") if task == "detect" else option("EFFORT", connection=True)
    )
    effort = (effort_override or ("" if task == "detect" else defaults["effort"])).lower()
    if effort and effort not in defaults["efforts"]:
        choices = ", ".join(sorted(defaults["efforts"]))
        raise ConfigError(f"{prefix}EFFORT for {provider} must be one of: {choices}.")
    thinking = (option("THINKING") or "adaptive").lower()
    if thinking not in {"adaptive", "off"}:
        raise ConfigError(f"{prefix}THINKING must be 'adaptive' or 'off'.")
    try:
        max_tokens = int(option("MAX_TOKENS") or DEFAULT_MAX_TOKENS)
    except ValueError:
        raise ConfigError(f"{prefix}MAX_TOKENS must be a positive integer.") from None
    if max_tokens <= 0:
        raise ConfigError(f"{prefix}MAX_TOKENS must be a positive integer.")
    if task == "detect" and not _env(prefix + "MAX_TOKENS"):
        max_tokens = min(max_tokens, 1200)

    key_env = option("API_KEY_ENV", connection=True) or f"{native_prefix}_API_KEY"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_env):
        raise ConfigError(
            f"{prefix}API_KEY_ENV must name an environment variable containing the key."
        )
    api_key = _env(key_env) or ""
    if require_key and not api_key:
        raise ConfigError(
            f"{key_env} is not set. Set it in your environment or .env; see env.example."
        )

    return Config(
        provider=provider,
        api_key=api_key,
        model=model or "",
        effort=effort,
        max_tokens=max_tokens,
        base_url=base_url,
        thinking=thinking,
        api_key_env=key_env,
    )
