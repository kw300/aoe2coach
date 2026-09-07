"""Web flow tests use synthetic metrics and fake model calls only."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("flask")

from aoe2coach import webapp  # noqa: E402
from aoe2coach.coach import CoachResult  # noqa: E402
from aoe2coach.config import ConfigError  # noqa: E402


@pytest.fixture
def setup(monkeypatch, tmp_path):
    metrics = SimpleNamespace(
        source_file="/private/replays/Game.aoe2record",
        map_name="Arabia",
        map_size="Tiny",
        recorded_at=None,
        recorded_at_source=None,
        backend="full",
        body_complete=True,
        rated=False,
        timeline=[{"at": "10:00", "type": "age_up", "label": "Alice reached Feudal"}],
        players=[
            SimpleNamespace(
                name="Alice",
                civilization="Franks",
                profile_id=101,
                color_id=0,
                team_id=1,
                result="won",
                labels={"feudal": "10:00", "castle": "20:00", "imperial": "—"},
                action_plan=[],
                build_order_comparison=[],
            ),
            SimpleNamespace(
                name="Bob",
                civilization="Britons",
                profile_id=102,
                color_id=1,
                team_id=2,
                result="lost",
                labels={"feudal": "11:00", "castle": "21:00", "imperial": "—"},
                action_plan=[],
                build_order_comparison=[],
            ),
        ],
        to_dict=lambda: {"duration_label": "32:10", "private_metric": "hidden-metrics"},
    )
    parse = Mock(return_value=object())
    monkeypatch.setattr(webapp, "parse_replay", parse)
    monkeypatch.setattr(webapp, "build_metrics", lambda _: metrics)
    monkeypatch.setattr(webapp, "_UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(webapp, "build_opening_message", Mock(return_value="hidden-metrics"))
    ratings = Mock(return_value={})
    monkeypatch.setattr("aoe2coach.elo.fetch_ratings", ratings)
    chats = []

    class FakeChat:
        def __init__(self):
            self.sent = []
            self.error = None
            chats.append(self)

        def send(self, message):
            if self.error:
                raise self.error
            self.sent.append(message)
            if len(self.sent) == 1:
                return CoachResult("## Opening advice", "analysis-model", 100, 20, 0, 0)
            return CoachResult(f"Reply to: {message}", "chat-model", None, None, None, None)

    monkeypatch.setattr(webapp, "CoachChat", FakeChat)
    app = webapp.create_app()
    app.testing = True
    return SimpleNamespace(
        app=app, client=app.test_client(), chats=chats, parse=parse, ratings=ratings
    )


def _preview(client):
    return client.post("/api/preview", json={"replay": "/private/Game.aoe2record"}).get_json()


def _open(client, focus="Alice", preview=None):
    return client.post(
        "/api/open", json={"replay": "/private/Game.aoe2record", "focus_player": focus}
    ).get_json()


def test_session_index_labels(monkeypatch):
    monkeypatch.setattr(webapp, "_listed_replays", lambda: [Path("My Cool Game.aoe2record")])
    client = webapp.create_app().test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert b"My Cool Game.aoe2record" in response.data
    assert b"Drag a" in response.data
    assert b"API key" not in response.data
    assert b"Download conversation" in response.data
    assert b"Input tokens:" in response.data


def test_index_escapes_replay_filename(monkeypatch):
    monkeypatch.setattr(
        webapp, "_listed_replays", lambda: [Path('<img onerror="evil">.aoe2record')]
    )
    page = webapp.create_app().test_client().get("/").text
    assert '<img onerror="evil">' not in page
    assert "&lt;img onerror=&quot;evil&quot;&gt;" in page


def test_preview_preserves_replay_context_without_constructing_chat(setup):
    data = _preview(setup.client)
    preview = data["preview"]
    assert [p["name"] for p in preview["players"]] == ["Alice", "Bob"]
    assert preview["duration_label"] == "32:10"
    assert preview["players"][0]["color"] == "#3c6eff"
    assert data["insights"]["comparison"]["players"][0]["name"] == "Alice"
    assert data["insights"]["timeline"][0]["at"] == "10:00"
    assert setup.chats == []
    assert "hidden-metrics" not in str(data)


def test_upload_previews_and_never_overwrites_same_name(setup):
    first = setup.client.post(
        "/api/upload", data={"file": (io.BytesIO(b"first"), "Game.aoe2record")}
    ).get_json()
    second = setup.client.post(
        "/api/upload", data={"file": (io.BytesIO(b"second"), "Game.aoe2record")}
    ).get_json()
    assert first["path"] != second["path"]
    assert Path(first["path"]).read_bytes() == b"first"
    assert Path(second["path"]).read_bytes() == b"second"
    assert setup.chats == []


@pytest.mark.parametrize("focus", ["Missing", "", [], 3])
def test_invalid_focus_never_calls_model(setup, focus):
    response = _open(setup.client, focus=focus)
    assert "Choose a player" in response["error"]
    assert setup.chats == []


@pytest.mark.parametrize("focus", ["Alice", None])
def test_open_passes_focus_and_returns_metadata_with_insights(setup, focus):
    preview = _preview(setup.client)
    result = _open(setup.client, focus=focus, preview=preview)
    assert result["report"] == "## Opening advice"
    assert result["model"] == "analysis-model"
    assert result["input_tokens"] == 100
    assert result["output_tokens"] == 20
    assert result["session_id"]
    assert setup.parse.call_count == 2
    assert webapp.build_opening_message.call_args.kwargs["focus_player"] == focus
    setup.ratings.assert_called_with([101, 102], timeout=3.0)


def test_direct_open_compatibility_returns_session_id(setup):
    result = setup.client.post(
        "/api/open", json={"replay": "Game.aoe2record", "focus_player": "Bob"}
    ).get_json()
    assert result["session_id"]
    assert webapp.build_opening_message.call_args.kwargs["focus_player"] == "Bob"


def test_followups_and_exports_are_isolated_for_same_replay(setup):
    preview = _preview(setup.client)
    first = _open(setup.client, preview=preview)
    other_tab = setup.app.test_client()
    second = _open(other_tab, focus="Bob", preview=preview)
    assert first["session_id"] != second["session_id"]
    reply = setup.client.post(
        "/api/chat", json={"session_id": first["session_id"], "message": "Alice-only question"}
    ).get_json()
    assert reply["model"] == "chat-model"
    assert reply["input_tokens"] is None and reply["output_tokens"] is None
    assert setup.chats[0].sent == ["hidden-metrics", "Alice-only question"]
    assert setup.chats[1].sent == ["hidden-metrics"]
    response = setup.client.get(f"/api/export/{first['session_id']}")
    exported = response.text
    assert response.mimetype == "text/markdown"
    assert 'attachment; filename="Game.conversation.md"' == response.headers["Content-Disposition"]
    assert "**Replay:** Game.aoe2record" in exported
    assert "**Coaching focus:** Alice" in exported
    assert "Alice (Franks), Bob (Britons)" in exported
    assert "Arabia" in exported and "32:10" in exported
    assert "## Opening advice" in exported
    assert "> Alice-only question" in exported
    assert "Model: analysis-model · Input tokens: 100 · Output tokens: 20" in exported
    assert "Model: chat-model · Input tokens: unavailable · Output tokens: unavailable" in exported
    for hidden in ["hidden-metrics", "/private/", "system_blocks", "api_key", "source_file"]:
        assert hidden not in exported
    second_export = other_tab.get(f"/api/export/{second['session_id']}").text
    assert "Alice-only question" not in second_export
    assert "**Coaching focus:** Bob" in second_export
    assert len(setup.chats[0].sent) == 2  # Downloading never calls the model.


def test_sessions_are_not_shared_between_app_instances(setup):
    result = _open(setup.client)
    other_app = webapp.create_app().test_client()
    assert other_app.get(f"/api/export/{result['session_id']}").status_code == 404


def test_failed_start_can_retry_preview(setup, monkeypatch):
    preview = _preview(setup.client)
    chat_class = webapp.CoachChat
    monkeypatch.setattr(
        webapp, "CoachChat", Mock(side_effect=ConfigError("Missing model key.\nHelp"))
    )
    assert _open(setup.client, preview=preview)["error"] == "Missing model key."
    monkeypatch.setattr(webapp, "CoachChat", chat_class)
    assert _open(setup.client, preview=preview)["session_id"]


def test_failed_followup_is_exported_safely_and_session_can_retry(setup):
    opened = _open(setup.client)
    setup.chats[0].error = RuntimeError("secret-key and /private/provider/request")
    result = setup.client.post(
        "/api/chat", json={"session_id": opened["session_id"], "message": "Question before failure"}
    ).get_json()
    assert "model request failed" in result["error"]
    exported = setup.client.get(f"/api/export/{opened['session_id']}").text
    assert "Question before failure" in exported
    assert "## Request failed" in exported
    assert "secret-key" not in exported and "/private/provider" not in exported
    setup.chats[0].error = None
    retry = setup.client.post(
        "/api/chat", json={"session_id": opened["session_id"], "message": "Try again"}
    ).get_json()
    assert retry["reply"] == "Reply to: Try again"


def test_empty_followup_does_not_call_model(setup):
    opened = _open(setup.client)
    response = setup.client.post(
        "/api/chat", json={"session_id": opened["session_id"], "message": "  "}
    ).get_json()
    assert response["error"] == "Enter a message first."
    assert len(setup.chats[0].sent) == 1


@pytest.mark.parametrize("body", [{}, {"replay": ""}, {"replay": []}, []])
def test_missing_preview_returns_error_without_model(setup, body):
    assert "error" in setup.client.post("/api/open", json=body).get_json()
    assert setup.chats == []


@pytest.mark.parametrize("body", [{}, [], {"session_id": []}, {"replay": "x", "message": "hi"}])
def test_session_invalid_chat_body(body):
    client = webapp.create_app().test_client()
    response = client.post("/api/chat", json=body)
    assert response.status_code == 200
    assert response.get_json()["error"] == "Open a replay first."


def test_session_bad_replay():
    client = webapp.create_app().test_client()
    response = client.post("/api/open", json={"replay": "/nonexistent/none.aoe2record"})
    assert "error" in response.get_json()


def test_parse_failure_does_not_call_model(setup):
    setup.parse.side_effect = ValueError("Unsupported replay.")
    assert _preview(setup.client)["error"] == "Unsupported replay."
    assert setup.chats == []


def test_session_missing_upload():
    client = webapp.create_app().test_client()
    assert client.post("/api/upload", data={}).get_json()["error"] == "No file uploaded."


def test_upload_wrong_extension_is_rejected_without_parsing(setup):
    response = setup.client.post("/api/upload", data={"file": (io.BytesIO(b"x"), "bad.txt")})
    assert response.get_json()["error"] == "Choose a .aoe2record file."
    setup.parse.assert_not_called()


def test_bad_upload_is_removed(setup):
    setup.parse.side_effect = ValueError("Broken replay.")
    response = setup.client.post(
        "/api/upload", data={"file": (io.BytesIO(b"bad"), "broken.aoe2record")}
    )
    assert response.get_json()["error"] == "Broken replay."
    assert list(webapp._UPLOAD_DIR.glob("*/*.aoe2record")) == []


def test_session_has_no_key_endpoint():
    client = webapp.create_app().test_client()
    assert client.post("/api/key", json={"key": "sk-ant-test"}).status_code == 404
