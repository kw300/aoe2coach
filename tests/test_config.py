"""Tests for provider/key configuration (BYO-model)."""

from __future__ import annotations

import pytest

from aoe2coach.config import ConfigError, load_config


def test_default_provider_is_anthropic(monkeypatch):
    monkeypatch.delenv("AOE2COACH_PROVIDER", raising=False)
    monkeypatch.delenv("AOE2COACH_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    c = load_config()
    assert c.provider == "anthropic"
    assert c.model == "claude-opus-4-7"
    assert c.base_url is None


def test_anthropic_missing_key_fails_fast(monkeypatch):
    # Don't let a developer's real .env leak in and mask the missing-key path.
    monkeypatch.setattr("aoe2coach.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("AOE2COACH_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        load_config()
    # …but metrics-only paths can skip the key requirement.
    assert load_config(require_key=False).provider == "anthropic"


def test_openai_requires_model(monkeypatch):
    monkeypatch.setenv("AOE2COACH_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("AOE2COACH_MODEL", raising=False)
    with pytest.raises(ConfigError):
        load_config()


def test_openai_config_resolves(monkeypatch):
    monkeypatch.setenv("AOE2COACH_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AOE2COACH_MODEL", "gpt-5.1")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    c = load_config()
    assert c.provider == "openai"
    assert c.model == "gpt-5.1"
    assert c.base_url.endswith("/v1")


def test_unknown_provider_errors(monkeypatch):
    monkeypatch.setenv("AOE2COACH_PROVIDER", "bogus")
    with pytest.raises(ConfigError):
        load_config(require_key=False)
