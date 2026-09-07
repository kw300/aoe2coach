"""CLI model selection reaches the same task routes as library/browser callers."""

from __future__ import annotations

from types import SimpleNamespace

from aoe2coach import cli
from aoe2coach.coach import CoachResult


def test_analyze_uses_analysis_connection(monkeypatch, tmp_path, capsys):
    replay = tmp_path / "example.aoe2record"
    replay.touch()
    metrics = SimpleNamespace(players=[])
    selected = SimpleNamespace(model="analysis-choice")
    seen = []

    def load(*, require_key, task):
        seen.append((require_key, task))
        return selected

    def coach(received_metrics, *, config, focus_player, **kwargs):
        assert received_metrics is metrics
        assert config is selected
        assert focus_player == "Alice"
        return CoachResult("Advice", model=config.model)

    monkeypatch.setattr("aoe2coach.config.load_config", load)
    monkeypatch.setattr("aoe2coach.parse_replay", lambda path: object())
    monkeypatch.setattr("aoe2coach.build_metrics", lambda parsed: metrics)
    monkeypatch.setattr("aoe2coach.coach.coach_replay", coach)
    assert cli.main(["analyze", str(replay), "--player", "Alice", "--no-elo", "--no-save"]) == 0
    assert seen == [(True, "analysis")]
    assert "analysis-choice" in capsys.readouterr().err


def test_trends_uses_trends_connection_and_no_coach_skips_config(monkeypatch, tmp_path, capsys):
    replay = tmp_path / "example.aoe2record"
    replay.touch()
    summary = SimpleNamespace(
        player="Alice",
        n_games=1,
        wins=1,
        losses=0,
        win_rate=1,
        avg_feudal_s=600,
        avg_idle_tc_s=None,
        feudal_direction="n/a",
        to_dict=lambda: {"player": "Alice"},
    )
    selected = SimpleNamespace(model="trends-choice")
    seen = []

    def load(*, require_key, task):
        seen.append((require_key, task))
        return selected

    def coach(received_summary, *, config, **kwargs):
        assert received_summary is summary
        assert config is selected
        return CoachResult("Practice plan", model=config.model)

    monkeypatch.setattr("aoe2coach.config.load_config", load)
    monkeypatch.setattr("aoe2coach.parse_replay", lambda path: object())
    monkeypatch.setattr("aoe2coach.build_metrics", lambda parsed: object())
    monkeypatch.setattr("aoe2coach.trends.aggregate", lambda metrics, player: summary)
    monkeypatch.setattr("aoe2coach.coach.coach_trends", coach)
    assert cli.main(["trends", str(replay), "--no-coach"]) == 0
    assert seen == []
    assert cli.main(["trends", str(replay)]) == 0
    assert seen == [(True, "trends")]
    assert "trends-choice" in capsys.readouterr().err
