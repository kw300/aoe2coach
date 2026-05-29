"""Tests for lightweight habit detection plumbing."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from aoe2coach.coach import _run_anthropic, _run_openai, detect_habits
from aoe2coach.config import Config


def test_detect_habits_parses_json_response(monkeypatch):
    def fake_run(_system, _user, *, config, stream, on_text):
        assert config.model == "claude-haiku-4-5"
        assert config.effort == ""
        return SimpleNamespace(
            text=(
                '{"habits":[{"label":"Spend wood earlier","player":"Me",'
                '"detail":"Floated wood.","priority":"high"}]}'
            ),
            model=config.model,
            cost_note="cheap",
        )

    monkeypatch.setattr("aoe2coach.coach._run", fake_run)
    metrics = SimpleNamespace(
        map_name="Arabia",
        duration_s=1800,
        recorded_at=None,
        backend="full",
        rated=True,
        matchup_context={},
        players=[],
        battles=[],
        timeline=[],
    )
    config = Config("anthropic", "test-key", "claude-opus-4-8", "medium", 8000)
    out = detect_habits(metrics, config=config, focus_player="Me")
    assert out["habits"][0]["label"] == "Spend wood earlier"
    assert out["model"] == "claude-haiku-4-5"


def test_detect_habits_uses_openai_default_detect_model(monkeypatch):
    def fake_run(_system, _user, *, config, stream, on_text):
        assert config.provider == "openai"
        assert config.model == "gpt-5.4-mini"
        return SimpleNamespace(text='{"habits":[]}', model=config.model, cost_note="cheap")

    monkeypatch.setattr("aoe2coach.coach._run", fake_run)
    metrics = SimpleNamespace(
        map_name="Arabia",
        duration_s=1800,
        recorded_at=None,
        backend="full",
        rated=True,
        matchup_context={},
        players=[],
        battles=[],
        timeline=[],
    )
    config = Config("openai", "test-key", "gpt-5.5", "medium", 8000)
    out = detect_habits(metrics, config=config, focus_player="Me")
    assert out["model"] == "gpt-5.4-mini"


def test_detect_habits_uses_custom_endpoint_full_model(monkeypatch):
    def fake_run(_system, _user, *, config, stream, on_text):
        assert config.provider == "openai"
        assert config.model == "local-strong"
        return SimpleNamespace(text='{"habits":[]}', model=config.model, cost_note="cheap")

    monkeypatch.setattr("aoe2coach.coach._run", fake_run)
    metrics = SimpleNamespace(
        map_name="Arabia",
        duration_s=1800,
        recorded_at=None,
        backend="full",
        rated=True,
        matchup_context={},
        players=[],
        battles=[],
        timeline=[],
    )
    config = Config(
        "openai", "test-key", "local-strong", "medium", 8000, "http://localhost:11434/v1"
    )
    out = detect_habits(metrics, config=config, focus_player="Me")
    assert out["model"] == "local-strong"


def test_openai_hosted_request_passes_reasoning_effort(monkeypatch):
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                model=kwargs["model"],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2),
            )

    class FakeOpenAI:
        def __init__(self, *, api_key, base_url=None):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    config = Config("openai", "sk-test", "gpt-5.5", "xhigh", 8000)
    _run_openai(
        [{"type": "text", "text": "system"}],
        [{"role": "user", "content": "hi"}],
        config,
        False,
        None,
    )
    assert calls[0]["reasoning_effort"] == "xhigh"


def test_openai_custom_endpoint_omits_reasoning_effort(monkeypatch):
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                model=kwargs["model"],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2),
            )

    class FakeOpenAI:
        def __init__(self, *, api_key, base_url=None):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    config = Config("openai", "sk-test", "local-strong", "xhigh", 8000, "http://localhost:11434/v1")
    _run_openai(
        [{"type": "text", "text": "system"}],
        [{"role": "user", "content": "hi"}],
        config,
        False,
        None,
    )
    assert "reasoning_effort" not in calls[0]


def test_anthropic_haiku_omits_adaptive_effort(monkeypatch):
    calls = []

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="ok")],
                model=kwargs["model"],
                usage=SimpleNamespace(
                    input_tokens=1,
                    output_tokens=2,
                    cache_read_input_tokens=0,
                    cache_creation_input_tokens=0,
                ),
            )

    class FakeAnthropic:
        def __init__(self, *, api_key):
            self.messages = FakeMessages()

    monkeypatch.setattr("aoe2coach.coach.anthropic.Anthropic", FakeAnthropic)
    config = Config("anthropic", "sk-test", "claude-haiku-4-5", "low", 1200)
    _run_anthropic(
        [{"type": "text", "text": "system"}],
        [{"role": "user", "content": "hi"}],
        config,
        False,
        None,
    )
    assert "thinking" not in calls[0]
    assert "output_config" not in calls[0]
