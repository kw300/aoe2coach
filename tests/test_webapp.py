"""Smoke test for the web chat UI. Needs only Flask (no API key, backend, or network)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("flask")

from aoe2coach import webapp  # noqa: E402


def test_index_lists_replays_and_dropzone(monkeypatch):
    monkeypatch.setattr(webapp, "_listed_replays", lambda: [Path("My Cool Game.aoe2record")])
    client = webapp.create_app().test_client()
    r = client.get("/")
    assert r.status_code == 200
    assert b"My Cool Game.aoe2record" in r.data
    assert b"Drag a" in r.data  # the drag-and-drop zone
    assert b'id="insights"' in r.data
    assert b"Practice Focus" in r.data
    assert b'id="leftResize"' in r.data
    assert b'id="rightResize"' in r.data
    assert b'data-vresize-key="list"' in r.data
    assert b"Detected</h2>" in r.data
    assert b"Run full analysis" in r.data
    assert b"Export session" in r.data
    assert b"id=\"exportSession\"" in r.data
    assert b"replace(/\\r\\n/g,'\\n')" in r.data
    assert b"flagship model" in r.data
    assert b"Opus" not in r.data
    assert b"Sonnet" not in r.data
    assert b"claude" not in r.data.lower()
    assert b"API key" not in r.data


def test_chat_without_open_session_is_graceful():
    client = webapp.create_app().test_client()
    r = client.post("/api/chat", json={"replay": "x", "message": "hi"})
    assert r.status_code == 200
    assert r.get_json()["error"] == "Open a replay first."


def test_open_bad_replay_returns_error():
    client = webapp.create_app().test_client()
    r = client.post("/api/open", json={"replay": "/nonexistent/none.aoe2record"})
    assert "error" in r.get_json()


def test_preview_bad_replay_returns_error():
    client = webapp.create_app().test_client()
    r = client.post("/api/preview", json={"replay": "/nonexistent/none.aoe2record"})
    assert "error" in r.get_json()


def test_upload_without_file_is_graceful():
    client = webapp.create_app().test_client()
    r = client.post("/api/upload", data={})
    assert r.get_json()["error"] == "No file uploaded."


def test_export_session_saves_markdown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = webapp.create_app().test_client()
    r = client.post(
        "/api/export-session",
        json={"filename": "My Game.md", "markdown": "# Session\n\nHello"},
    )
    out = tmp_path / "reports" / "session-exports" / "My_Game.md"
    assert r.get_json()["path"] == str(out)
    assert out.read_text(encoding="utf-8") == "# Session\n\nHello\n"


def test_minimap_without_replay_is_graceful():
    client = webapp.create_app().test_client()
    r = client.get("/api/minimap")
    assert r.status_code == 400
    assert r.get_json()["error"] == "No replay provided."


def test_web_insights_keeps_full_timeline():
    metrics = SimpleNamespace(
        matchup_context={},
        timeline=[{"at": f"0:{i:02d}", "label": str(i)} for i in range(20)],
        players=[],
    )
    insights = webapp._web_insights(metrics)
    assert len(insights["timeline"]) == 20
    assert "matchup" not in insights


def test_web_insights_does_not_hardcode_detected_habits():
    player = SimpleNamespace(
        name="Me",
        civilization="Romans",
        profile_id=123,
        opening="Unclear opening",
        opening_confidence="high",
        action_plan=[
            {
                "focus": "Town Center uptime",
                "why": "90s estimated idle TC",
                "target": "Under 45s idle TC",
            }
        ],
        build_order_comparison=[],
    )
    metrics = SimpleNamespace(matchup_context={}, timeline=[], players=[player])
    assert webapp._web_insights(metrics)["detected_habits"] == []


def test_web_insights_builds_player_comparison_table():
    player_a = SimpleNamespace(
        name="Me",
        civilization="Romans",
        profile_id=123,
        color_id=0,
        opening="Unclear opening",
        opening_confidence="high",
        action_plan=[],
        build_order_comparison=[
            {"checkpoint": "Stable", "status": "late"},
            {"checkpoint": "Feudal", "status": "on_time"},
        ],
        estimated_idle_tc_s=80,
        villagers_16m=34,
        high_float_s=190,
        feudal_time_s=700,
        castle_time_s=1100,
        eapm=38,
        command_actions_per_min=30.0,
    )
    player_b = SimpleNamespace(
        name="Opponent",
        civilization="Khmer",
        profile_id=456,
        color_id=1,
        opening="Unclear opening",
        opening_confidence="high",
        action_plan=[],
        build_order_comparison=[],
        estimated_idle_tc_s=40,
        villagers_16m=30,
        high_float_s=220,
        feudal_time_s=720,
        castle_time_s=1050,
        eapm=45,
        command_actions_per_min=32.0,
    )
    metrics = SimpleNamespace(map_name="Arabia", timeline=[], players=[player_a, player_b])
    insights = webapp._web_insights(metrics, {123: {"rm_1v1_rating": 1120}})
    compare = insights["comparison"]
    rows = {row["metric"]: row for row in compare["rows"]}

    assert compare["players"][0]["rating"] == 1120
    assert compare["players"][1]["rating"] is None
    assert rows["TC idle"]["values"] == ["80s idle", "40s idle"]
    assert rows["TC idle"]["classes"] == ["bad", "ok"]
    assert rows["Villagers @16"]["classes"] == ["ok", "bad"]
    assert "Spending" not in rows
    assert "Opening issues" not in rows


def test_web_preview_exposes_focus_choices():
    player = SimpleNamespace(
        name="Me",
        civilization="Romans",
        color_id=0,
        team_id=1,
        profile_id=123,
        result="won",
        opening="Unclear opening",
        labels={"feudal": "10:40", "castle": "19:00", "imperial": "—"},
    )
    metrics = SimpleNamespace(
        source_file="x.aoe2record",
        map_name="Arabia",
        map_size="Tiny",
        recorded_at="2025-08-16T12:07:09",
        recorded_at_source="replay",
        backend="full",
        body_complete=True,
        rated=True,
        players=[player],
        to_dict=lambda: {"duration_label": "32:00"},
    )
    preview = webapp._web_preview(metrics)
    assert preview["map_name"] == "Arabia"
    assert preview["recorded_at_label"] == "2025-08-16 12:07"
    assert preview["players"][0]["color"] == "#3c6eff"
    assert preview["players"][0]["name"] == "Me"


def test_date_label_handles_missing_and_iso_values():
    assert webapp._date_label(None) is None
    assert webapp._date_label("2025-08-16T12:07:09") == "2025-08-16 12:07"


def test_player_color_maps_replay_color_id():
    assert webapp._player_color(0) == "#3c6eff"
    assert webapp._player_color(1) == "#e63232"
    assert webapp._player_color(4) == "#28c8e6"
    assert webapp._player_color_value("Blue", 1) == "#3c6eff"
    assert webapp._player_color_value("Teal", 4) == "#28c8e6"
    assert webapp._player_color(None) is None


def test_practice_focus_sanitizes_habits():
    habits = webapp._clean_habits(["  Stop floating wood  ", "", "stop floating wood", 123])
    assert habits == ["Stop floating wood", "123"]
    block = webapp._practice_focus_block(habits)
    assert "User-pinned practice focus" in block
    assert "- Stop floating wood" in block
    detected_block = webapp._practice_focus_block([], ["Late farms"])
    assert "Lightweight-model candidate habits" in detected_block
    assert "- Late farms" in detected_block


def test_open_session_sends_focus_player_and_habits(monkeypatch):
    calls = {}

    class FakeChat:
        def send(self, text):
            calls["opening_text"] = text
            return SimpleNamespace(text="report")

    metrics = SimpleNamespace(matchup_context={}, timeline=[], players=[])
    monkeypatch.setattr(webapp, "CoachChat", FakeChat)
    monkeypatch.setattr(webapp, "parse_replay", lambda _path: object())
    monkeypatch.setattr(webapp, "build_metrics", lambda _parsed: metrics)

    def fake_opening(_metrics, *, focus_player, elo, trends):
        calls["focus_player"] = focus_player
        return "opening"

    monkeypatch.setattr(webapp, "build_opening_message", fake_opening)
    result = webapp._open_session(
        "x",
        ["Stop floating wood"],
        focus_player="Me",
        detected_habits=["Late farms"],
    )
    assert result["report"] == "report"
    assert calls["focus_player"] == "Me"
    assert "Stop floating wood" in calls["opening_text"]
    assert "Late farms" in calls["opening_text"]


def test_detect_habit_route_uses_model_helper(monkeypatch):
    metrics = SimpleNamespace(matchup_context={}, timeline=[], players=[])
    monkeypatch.setattr(webapp, "parse_replay", lambda _path: object())
    monkeypatch.setattr(webapp, "build_metrics", lambda _parsed: metrics)
    monkeypatch.setattr(
        webapp,
        "detect_habits",
        lambda _metrics, focus_player=None: {
            "habits": [{"label": "Spend wood sooner", "player": focus_player or "both"}],
            "model": "cheap-model",
        },
    )
    client = webapp.create_app().test_client()
    r = client.post("/api/detect-habits", json={"replay": "x", "focus_player": "Me"})
    assert r.get_json()["habits"][0]["player"] == "Me"
    assert r.get_json()["model"] == "cheap-model"


def test_web_ui_does_not_accept_keys():
    client = webapp.create_app().test_client()
    r = client.post("/api/key", json={"key": "sk-ant-test"})
    assert r.status_code == 404
