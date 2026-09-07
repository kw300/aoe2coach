"""Deterministic provider, task inheritance, validation, and secret-handling checks."""

from __future__ import annotations

import os

import pytest

from aoe2coach.config import ConfigError, load_config


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    # Real .env files and developer provider settings must never influence these tests.
    monkeypatch.setattr("aoe2coach.config.load_dotenv", lambda: None)
    for name in os.environ:
        if name.startswith(("AOE2COACH_", "ANTHROPIC_", "OPENAI_")):
            monkeypatch.delenv(name)


def test_default_provider_is_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-key")
    c = load_config()
    assert c.provider == "anthropic"
    assert c.model == "claude-opus-4-8"
    assert c.effort == "high"
    assert c.base_url is None
    assert c.thinking == "adaptive"
    assert c.api_key_env == "ANTHROPIC_API_KEY"
    assert "test-only-key" not in repr(c)


def test_anthropic_missing_key_fails_fast():
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY is not set"):
        load_config()
    assert load_config(require_key=False).provider == "anthropic"


def test_openai_key_auto_selects_provider(monkeypatch):
    monkeypatch.setattr("aoe2coach.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("AOE2COACH_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("AOE2COACH_MODEL", raising=False)
    c = load_config()
    assert c.provider == "openai"
    assert c.model == "gpt-5.5"
    assert c.effort == "high"


def test_openai_custom_endpoint_requires_model(monkeypatch):
    monkeypatch.setenv("AOE2COACH_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.delenv("AOE2COACH_MODEL", raising=False)
    with pytest.raises(ConfigError):
        load_config()
    assert load_config(require_key=False).model == ""


def test_openai_config_resolves(monkeypatch):
    monkeypatch.setenv("AOE2COACH_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setenv("AOE2COACH_MODEL", "user-selected-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    c = load_config()
    assert c.provider == "openai"
    assert c.model == "user-selected-model"
    assert c.base_url == "https://openrouter.ai/api/v1"


def test_unknown_provider_errors(monkeypatch):
    monkeypatch.setenv("AOE2COACH_PROVIDER", "bogus")
    with pytest.raises(ConfigError):
        load_config(require_key=False)


def test_provider_specific_effort_validation(monkeypatch):
    monkeypatch.setenv("AOE2COACH_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("AOE2COACH_EFFORT", "none")
    with pytest.raises(ConfigError):
        load_config()

    monkeypatch.setenv("AOE2COACH_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AOE2COACH_EFFORT", "max")
    with pytest.raises(ConfigError):
        load_config()


@pytest.mark.parametrize("task", ["analysis", "chat", "trends"])
def test_tasks_inherit_default_and_independent_overrides(monkeypatch, task):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-key")
    monkeypatch.setenv("AOE2COACH_MODEL", "default-model")
    monkeypatch.setenv("AOE2COACH_EFFORT", "high")
    monkeypatch.setenv("AOE2COACH_MAX_TOKENS", "700")
    monkeypatch.setenv("AOE2COACH_THINKING", "off")
    assert load_config(task=task) == load_config()
    monkeypatch.setenv(f"AOE2COACH_{task.upper()}_MODEL", "task-model")
    chosen = load_config(task=task)
    assert chosen.model == "task-model"
    assert chosen.max_tokens == 700
    assert chosen.effort == "high"
    assert chosen.thinking == "off"
    assert load_config().model == "default-model"


def test_all_task_options_override_default(monkeypatch):
    values = {
        "AOE2COACH_CHAT_PROVIDER": "openai",
        "AOE2COACH_CHAT_MODEL": "chat-model",
        "AOE2COACH_CHAT_BASE_URL": "http://localhost:1234/v1",
        "AOE2COACH_CHAT_API_KEY_ENV": "TEST_CHAT_KEY",
        "AOE2COACH_CHAT_EFFORT": "low",
        "AOE2COACH_CHAT_THINKING": "off",
        "AOE2COACH_CHAT_MAX_TOKENS": "512",
        "TEST_CHAT_KEY": "task-test-key",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    c = load_config(task="chat")
    assert (c.provider, c.model, c.effort, c.thinking) == (
        "openai",
        "chat-model",
        "low",
        "off",
    )
    assert c.base_url == "http://localhost:1234/v1"
    assert c.api_key == "task-test-key"
    assert c.api_key_env == "TEST_CHAT_KEY"
    assert c.max_tokens == 512


def test_provider_change_does_not_inherit_model_key_or_endpoint(monkeypatch):
    for name, value in {
        "AOE2COACH_PROVIDER": "anthropic",
        "AOE2COACH_MODEL": "anthropic-model",
        "AOE2COACH_BASE_URL": "https://anthropic-proxy.example/v1",
        "AOE2COACH_API_KEY_ENV": "TEST_DEFAULT_KEY",
        "TEST_DEFAULT_KEY": "default-test-key",
        "AOE2COACH_CHAT_PROVIDER": "openai",
        "OPENAI_BASE_URL": "http://localhost:1234/v1",
        "OPENAI_API_KEY": "openai-test-key",
    }.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError, match="AOE2COACH_CHAT_MODEL is required"):
        load_config(task="chat")
    monkeypatch.setenv("AOE2COACH_CHAT_MODEL", "chat-model")
    c = load_config(task="chat")
    assert c.api_key == "openai-test-key"
    assert c.api_key_env == "OPENAI_API_KEY"
    assert c.base_url == "http://localhost:1234/v1"


def test_switch_to_anthropic_uses_its_default_model(monkeypatch):
    monkeypatch.setenv("AOE2COACH_PROVIDER", "openai")
    monkeypatch.setenv("AOE2COACH_MODEL", "openai-model")
    monkeypatch.setenv("AOE2COACH_ANALYSIS_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-key")
    assert load_config(task="analysis").model == "claude-opus-4-8"


def test_same_provider_inherits_connection_overrides_and_blank_values(monkeypatch):
    monkeypatch.setenv("AOE2COACH_API_KEY_ENV", "TEST_DEFAULT_KEY")
    monkeypatch.setenv("TEST_DEFAULT_KEY", "test-only-key")
    monkeypatch.setenv("AOE2COACH_BASE_URL", "https://proxy.example/v1")
    monkeypatch.setenv("AOE2COACH_CHAT_PROVIDER", " ANTHROPIC ")
    monkeypatch.setenv("AOE2COACH_CHAT_MODEL", "  ")
    assert load_config(task="chat") == load_config()


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        ("PROVIDER", "bogus", "PROVIDER"),
        ("MAX_TOKENS", "many", "positive integer"),
        ("MAX_TOKENS", "0", "positive integer"),
        ("MAX_TOKENS", "-2", "positive integer"),
        ("EFFORT", "extra", "EFFORT"),
        ("THINKING", "enabled", "THINKING"),
        ("API_KEY_ENV", "sk-pasted-secret", "environment variable"),
        ("BASE_URL", "ftp://example.test", "HTTP\\(S\\)"),
        ("BASE_URL", "https://user:secret@example.test", "credentials"),
        ("BASE_URL", "https://example.test?key=secret", "credentials"),
        ("BASE_URL", "http://localhost:invalid/v1", "HTTP\\(S\\)"),
    ],
)
def test_bad_config_has_actionable_errors_without_values(monkeypatch, name, value, expected):
    monkeypatch.setenv(f"AOE2COACH_CHAT_{name}", value)
    with pytest.raises(ConfigError, match=expected) as exc:
        load_config(require_key=False, task="chat")
    assert value not in str(exc.value)


def test_unknown_task_is_rejected():
    with pytest.raises(ConfigError, match="Unknown coaching task"):
        load_config(require_key=False, task="typo")


def test_task_key_error_names_selected_environment_variable(monkeypatch):
    monkeypatch.setenv("AOE2COACH_CHAT_API_KEY_ENV", "TEST_MISSING_CHAT_KEY")
    monkeypatch.delenv("TEST_MISSING_CHAT_KEY", raising=False)
    with pytest.raises(ConfigError, match="TEST_MISSING_CHAT_KEY is not set"):
        load_config(task="chat")


@pytest.mark.parametrize("task", ["analysis", "chat", "trends"])
def test_tasks_respect_automatic_openai_provider(monkeypatch, task):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    chosen = load_config(task=task)
    assert chosen.provider == "openai"
    assert chosen.model == "gpt-5.5"
    assert chosen.effort == "high"


def test_anthropic_key_wins_provider_auto_detection(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    assert load_config(task="analysis").provider == "anthropic"


def test_provider_change_resets_provider_specific_effort(monkeypatch):
    monkeypatch.setenv("AOE2COACH_PROVIDER", "anthropic")
    monkeypatch.setenv("AOE2COACH_EFFORT", "max")
    monkeypatch.setenv("AOE2COACH_CHAT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    chosen = load_config(task="chat")
    assert chosen.model == "gpt-5.5"
    assert chosen.effort == "high"


@pytest.mark.parametrize(
    ("provider", "model"),
    [("anthropic", "claude-haiku-4-5"), ("openai", "gpt-5.4-mini")],
)
def test_detection_keeps_cheap_provider_defaults(monkeypatch, provider, model):
    monkeypatch.setenv("AOE2COACH_PROVIDER", provider)
    monkeypatch.setenv(f"{provider.upper()}_API_KEY", "test-only-key")
    monkeypatch.setenv("AOE2COACH_MODEL", "expensive-report-model")
    monkeypatch.setenv("AOE2COACH_EFFORT", "high")
    chosen = load_config(task="detect")
    assert chosen.model == model
    assert chosen.effort == ""
    assert chosen.max_tokens == 1200


def test_detection_custom_endpoint_uses_configured_model(monkeypatch):
    monkeypatch.setenv("AOE2COACH_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("AOE2COACH_MODEL", "local-model")
    monkeypatch.setenv("AOE2COACH_MAX_TOKENS", "700")
    chosen = load_config(task="detect")
    assert chosen.model == "local-model"
    assert chosen.max_tokens == 700
    monkeypatch.setenv("AOE2COACH_DETECT_MODEL", "local-small-model")
    assert load_config(task="detect").model == "local-small-model"


def test_detection_routes_independently_with_explicit_options(monkeypatch):
    monkeypatch.setenv("AOE2COACH_PROVIDER", "anthropic")
    monkeypatch.setenv("AOE2COACH_API_KEY_ENV", "UNUSED_ANALYSIS_KEY")
    monkeypatch.setenv("AOE2COACH_DETECT_PROVIDER", "openai")
    monkeypatch.setenv("AOE2COACH_DETECT_MODEL", "chosen-detect-model")
    monkeypatch.setenv("AOE2COACH_DETECT_API_KEY_ENV", "TEST_DETECT_KEY")
    monkeypatch.setenv("TEST_DETECT_KEY", "test-only-key")
    monkeypatch.setenv("AOE2COACH_DETECT_EFFORT", "low")
    monkeypatch.setenv("AOE2COACH_DETECT_MAX_TOKENS", "1800")
    chosen = load_config(task="detect")
    assert chosen.provider == "openai"
    assert chosen.model == "chosen-detect-model"
    assert chosen.api_key_env == "TEST_DETECT_KEY"
    assert chosen.effort == "low"
    assert chosen.max_tokens == 1800
