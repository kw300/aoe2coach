"""Model routing and provider response checks with no live requests."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from aoe2coach import coach
from aoe2coach.config import Config, ConfigError


def config(model="analysis-model", provider="anthropic", **options):
    return Config(provider, "test-only-key", model, "medium", 8000, **options)


def result(model="served-model"):
    return coach.CoachResult("advice", model, 10, 20, 0, 0)


def test_replay_and_trends_use_their_task_assignment(monkeypatch):
    loader = Mock(side_effect=lambda **kwargs: config(kwargs["task"]))
    run = Mock(return_value=result())
    monkeypatch.setattr(coach, "load_config", loader)
    monkeypatch.setattr(coach, "_run", run)
    monkeypatch.setattr(coach, "_user_content", lambda *args: "metrics")
    coach.coach_replay(None)
    assert run.call_args.kwargs["config"].model == "analysis"
    coach.coach_trends(SimpleNamespace(to_dict=lambda: {"games": 2}))
    assert run.call_args.kwargs["config"].model == "trends"
    assert [call.kwargs["task"] for call in loader.call_args_list] == [
        "analysis",
        "trends",
    ]


def test_explicit_config_pins_replay_and_trends(monkeypatch):
    chosen = config("pinned")
    loader = Mock(side_effect=AssertionError("explicit config must bypass environment"))
    run = Mock(return_value=result())
    monkeypatch.setattr(coach, "load_config", loader)
    monkeypatch.setattr(coach, "_run", run)
    monkeypatch.setattr(coach, "_user_content", lambda *args: "metrics")
    coach.coach_replay(None, config=chosen)
    assert run.call_args.kwargs["config"] is chosen
    coach.coach_trends(SimpleNamespace(to_dict=lambda: {}), config=chosen)
    assert run.call_args.kwargs["config"] is chosen
    loader.assert_not_called()


def test_chat_resolves_followup_only_when_used_and_keeps_history_across_providers(
    monkeypatch,
):
    analysis = config()
    chat = config("followup-model", provider="openai")
    loader = Mock(side_effect=[analysis, chat])
    run = Mock(side_effect=[result("analysis-served"), result("followup-served")])
    monkeypatch.setattr(coach, "load_config", loader)
    monkeypatch.setattr(coach, "_run_messages", run)
    session = coach.CoachChat()
    loader.assert_called_once_with(require_key=True, task="analysis")
    opening = session.send("analyze metrics")
    loader.assert_called_once()
    followup = session.send("what should I practice?")
    assert (opening.model, followup.model) == ("analysis-served", "followup-served")
    loader.assert_called_with(require_key=True, task="chat")
    assert run.call_args.kwargs["config"] is chat
    assert run.call_args.args[1] == [
        {"role": "user", "content": "analyze metrics"},
        {"role": "assistant", "content": "advice"},
        {"role": "user", "content": "what should I practice?"},
    ]
    assert len(session.messages) == 4
    assert session.config is chat


def test_explicit_config_pins_every_chat_turn(monkeypatch):
    loader = Mock(side_effect=AssertionError("explicit config must bypass environment"))
    run = Mock(return_value=result())
    chosen = config("pinned")
    monkeypatch.setattr(coach, "load_config", loader)
    monkeypatch.setattr(coach, "_run_messages", run)
    session = coach.CoachChat(config=chosen)
    session.send("opening")
    session.send("followup")
    assert all(call.kwargs["config"] is chosen for call in run.call_args_list)
    loader.assert_not_called()


def test_failed_opening_is_retried_with_analysis_and_no_duplicate_turn(monkeypatch):
    loader = Mock(return_value=config())
    run = Mock(side_effect=[RuntimeError("offline"), result()])
    monkeypatch.setattr(coach, "load_config", loader)
    monkeypatch.setattr(coach, "_run_messages", run)
    session = coach.CoachChat()
    with pytest.raises(RuntimeError, match="offline"):
        session.send("opening")
    assert session.messages == []
    session.send("opening")
    loader.assert_called_once_with(require_key=True, task="analysis")
    assert run.call_args.args[1] == [{"role": "user", "content": "opening"}]
    assert len(session.messages) == 2


def test_failed_followup_config_and_request_leave_history_and_active_config_intact(
    monkeypatch,
):
    analysis, chat = config(), config("chat-model")
    loader = Mock(side_effect=[analysis, ConfigError("chat key missing"), chat, chat])
    run = Mock(side_effect=[result(), RuntimeError("offline"), result()])
    monkeypatch.setattr(coach, "load_config", loader)
    monkeypatch.setattr(coach, "_run_messages", run)
    session = coach.CoachChat()
    session.send("opening")
    opening_history = list(session.messages)
    with pytest.raises(ConfigError, match="chat key missing"):
        session.send("followup")
    assert session.messages == opening_history
    with pytest.raises(RuntimeError, match="offline"):
        session.send("followup")
    assert session.messages == opening_history
    assert session.config is analysis
    session.send("followup")
    assert len(session.messages) == 4
    assert session.config is chat


@pytest.mark.parametrize("thinking", ["adaptive", "off"])
@pytest.mark.parametrize("stream", [False, True])
def test_anthropic_request_options_and_response_metadata(monkeypatch, thinking, stream):
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking"),
            SimpleNamespace(type="text", text="advice"),
        ],
        model="served-snapshot",
        usage=SimpleNamespace(
            input_tokens=11,
            output_tokens=12,
            cache_read_input_tokens=13,
            cache_creation_input_tokens=0,
        ),
    )
    create = Mock(return_value=response)
    stream_state = SimpleNamespace(text_stream=["ad", "vice"], get_final_message=lambda: response)
    stream_context = Mock()
    stream_context.__enter__ = Mock(return_value=stream_state)
    stream_context.__exit__ = Mock(return_value=False)
    stream_call = Mock(return_value=stream_context)
    client = Mock(
        return_value=SimpleNamespace(messages=SimpleNamespace(create=create, stream=stream_call))
    )
    monkeypatch.setattr(coach.anthropic, "Anthropic", client)
    chosen = config(thinking=thinking, base_url="https://proxy.example/v1")
    on_text = Mock()
    response_result = coach._run_messages(
        [{"type": "text", "text": "system"}],
        [{"role": "user", "content": "question"}],
        config=chosen,
        stream=stream,
        on_text=on_text,
    )
    client.assert_called_once_with(api_key="test-only-key", base_url="https://proxy.example/v1")
    request = (stream_call if stream else create).call_args.kwargs
    assert request["model"] == "analysis-model"
    assert request["max_tokens"] == 8000
    if thinking == "adaptive":
        assert request["thinking"] == {"type": "adaptive"}
        assert request["output_config"] == {"effort": "medium"}
    else:
        assert "thinking" not in request
        assert "output_config" not in request
    assert response_result.to_dict() == {
        "model": "served-snapshot",
        "input_tokens": 11,
        "output_tokens": 12,
        "cache_read_tokens": 13,
        "cache_write_tokens": 0,
    }
    assert response_result.text == "advice"
    if stream:
        assert [call.args[0] for call in on_text.call_args_list] == ["ad", "vice"]


def mock_openai(monkeypatch, response):
    create = Mock(return_value=response)
    client = Mock(
        return_value=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
    )
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=client))
    return client, create


@pytest.mark.parametrize("has_usage", [False, True])
def test_openai_response_and_minimal_provider_options(monkeypatch, has_usage):
    usage = (
        SimpleNamespace(
            prompt_tokens=25,
            completion_tokens=8,
            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        )
        if has_usage
        else None
    )
    response = SimpleNamespace(
        model="served-openai-model",
        usage=usage,
        choices=[SimpleNamespace(message=SimpleNamespace(content="advice"))],
    )
    client, create = mock_openai(monkeypatch, response)
    chosen = config("openai-model", provider="openai", base_url="http://localhost:1234/v1")
    answer = coach._run_messages(
        [{"type": "text", "text": "system", "cache_control": {"type": "ephemeral"}}],
        [{"role": "user", "content": "question"}],
        config=chosen,
        stream=False,
        on_text=None,
    )
    client.assert_called_once_with(api_key="test-only-key", base_url="http://localhost:1234/v1")
    create.assert_called_once_with(
        model="openai-model",
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "question"},
        ],
    )
    assert answer.model == "served-openai-model"
    assert answer.input_tokens == (25 if has_usage else None)
    assert answer.output_tokens == (8 if has_usage else None)
    assert answer.cache_read_tokens == (0 if has_usage else None)
    assert answer.cache_write_tokens is None


@pytest.mark.parametrize("has_usage", [False, True])
def test_openai_stream_accepts_usage_only_chunks_and_does_not_invent_usage(monkeypatch, has_usage):
    chunks = [
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="advice"))],
            model="stream-model",
        )
    ]
    if has_usage:
        chunks.append(
            SimpleNamespace(
                choices=[],
                usage=SimpleNamespace(
                    prompt_tokens=30,
                    completion_tokens=10,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=20),
                ),
            )
        )
    mock_openai(monkeypatch, iter(chunks))
    on_text = Mock()
    answer = coach._run_openai([], [], config(provider="openai"), True, on_text)
    assert answer.text == "advice"
    assert answer.model == "stream-model"
    assert answer.input_tokens == (30 if has_usage else None)
    assert answer.output_tokens == (10 if has_usage else None)
    assert answer.cache_read_tokens == (20 if has_usage else None)
    on_text.assert_called_once_with("advice")


def test_missing_anthropic_usage_is_unavailable(monkeypatch):
    response = SimpleNamespace(content=[SimpleNamespace(type="text", text="advice")])
    monkeypatch.setattr(
        coach.anthropic,
        "Anthropic",
        Mock(
            return_value=SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: response))
        ),
    )
    answer = coach._run_anthropic([], [], config(), False, None)
    assert answer.model == "analysis-model"
    assert all(value is None for name, value in answer.to_dict().items() if name != "model")
    assert "token usage unavailable" in answer.cost_note
    assert "cache usage unavailable" in answer.cost_note
    assert "cache miss" not in answer.cost_note


def test_zero_usage_is_distinct_from_unavailable():
    answer = coach.CoachResult("", "model", 0, 0, 0, 0)
    assert "in 0 / out 0 tokens" in answer.cost_note
    assert "cache read 0 / written 0 tokens" in answer.cost_note
    assert "first run" not in answer.cost_note
    partial = coach.CoachResult("", "model", output_tokens=4)
    assert "in unavailable / out 4 tokens" in partial.cost_note


def test_streaming_hosted_openai_keeps_reasoning_effort(monkeypatch):
    chunks = [
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="advice"))],
            model="served-model",
        )
    ]
    _, create = mock_openai(monkeypatch, iter(chunks))
    answer = coach._run_openai([], [], config(provider="openai"), True, None)
    assert create.call_args.kwargs["reasoning_effort"] == "medium"
    assert create.call_args.kwargs["stream"] is True
    assert answer.text == "advice"
    assert answer.input_tokens is None
