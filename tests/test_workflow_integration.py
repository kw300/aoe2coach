"""The replay-first web workflow reaches each configured model task."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("flask")

from aoe2coach import coach, webapp  # noqa: E402
from aoe2coach.coach import CoachResult  # noqa: E402
from aoe2coach.parse import ParsedReplay, PlayerReplay  # noqa: E402


def test_preview_detection_analysis_followup_and_export_use_real_routing(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith("AOE2COACH_") or name in {
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_BASE_URL",
            "OPENAI_BASE_URL",
        }:
            monkeypatch.delenv(name)
    monkeypatch.setattr("aoe2coach.config.load_dotenv", lambda: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "workflow-test-only")
    for task in ("ANALYSIS", "CHAT", "DETECT"):
        monkeypatch.setenv(f"AOE2COACH_{task}_MODEL", f"{task.lower()}-test-model")

    replay = tmp_path / "workflow.aoe2record"
    replay.touch()
    parsed = ParsedReplay(
        path=str(replay),
        backend="full",
        game_version="synthetic",
        build=1,
        map_name="Arabia",
        map_id=9,
        map_size="Tiny",
        diplomacy="1v1",
        duration_ms=1_200_000,
        rated=False,
        speed=1.7,
        population_limit=200,
        body_complete=True,
        players=[
            PlayerReplay(
                number=1,
                name="Alice",
                civ_id=1,
                civilization="Britons",
                profile_id=None,
                color_id=0,
                color_name="blue",
                team_id=1,
            ),
            PlayerReplay(
                number=2,
                name="Bob",
                civ_id=2,
                civilization="Franks",
                profile_id=None,
                color_id=1,
                color_name="red",
                team_id=2,
            ),
        ],
    )
    monkeypatch.setattr(webapp, "parse_replay", lambda _: parsed)
    monkeypatch.setattr(webapp, "_fetch_elo", lambda *args, **kwargs: {})
    calls = []

    def run(system, messages, *, config, **kwargs):
        calls.append((config.model, messages))
        if config.model == "detect-test-model":
            return CoachResult(
                '{"habits":[{"label":"Keep producing villagers","player":"Alice",'
                '"detail":"Practice a consistent opening","priority":"high"}]}',
                config.model,
                50,
                15,
            )
        return CoachResult("Coaching response", config.model, 100, 20)

    monkeypatch.setattr(coach, "_run_messages", run)
    client = webapp.create_app().test_client()
    preview = client.post("/api/preview", json={"replay": str(replay)}).get_json()
    assert "preview" in preview
    assert calls == []

    detected = client.post(
        "/api/detect-habits", json={"replay": str(replay), "focus_player": "Alice"}
    ).get_json()
    assert detected["model"] == "detect-test-model"
    assert detected["habits"][0]["label"] == "Keep producing villagers"

    opened = client.post(
        "/api/open",
        json={
            "replay": str(replay),
            "focus_player": "Alice",
            "habits": ["Spend resources"],
            "detected_habits": ["Keep producing villagers"],
        },
    ).get_json()
    assert opened["model"] == "analysis-test-model"
    assert opened["input_tokens"] == 100
    assert "Spend resources" in calls[-1][1][0]["content"]

    replied = client.post(
        "/api/chat", json={"session_id": opened["session_id"], "message": "My next drill?"}
    ).get_json()
    assert replied["model"] == "chat-test-model"
    assert [model for model, _ in calls] == [
        "detect-test-model",
        "analysis-test-model",
        "chat-test-model",
    ]
    assert len(calls[-1][1]) == 3
    assert "My next drill?" in calls[-1][1][-1]["content"]

    exported = client.get(f"/api/export/{opened['session_id']}")
    assert exported.status_code == 200
    for visible in ["Alice", "My next drill?", "analysis-test-model", "chat-test-model"]:
        assert visible in exported.text
    assert "workflow-test-only" not in exported.text
    assert "Here are the parsed metrics" not in exported.text
    assert len(calls) == 3
