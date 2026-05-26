"""Smoke test for the web chat UI. Needs only Flask (no API key, backend, or network)."""

from __future__ import annotations

from pathlib import Path

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


def test_upload_without_file_is_graceful():
    client = webapp.create_app().test_client()
    r = client.post("/api/upload", data={})
    assert r.get_json()["error"] == "No file uploaded."


def test_web_ui_does_not_accept_keys():
    client = webapp.create_app().test_client()
    r = client.post("/api/key", json={"key": "sk-ant-test"})
    assert r.status_code == 404
