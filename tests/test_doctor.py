"""Setup diagnostics are offline, actionable, and safe to paste into an issue."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from aoe2coach import cli, doctor
from aoe2coach.config import ConfigError


@pytest.fixture(autouse=True)
def local_setup(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(doctor, "_installed", lambda _: False)
    monkeypatch.setattr(doctor, "_detect_backend", lambda: "full")
    monkeypatch.setattr(doctor, "_importable", lambda _: True)
    monkeypatch.setattr(doctor, "find_replays", lambda: [])
    monkeypatch.setattr(
        doctor,
        "load_config",
        lambda **kwargs: SimpleNamespace(
            provider="anthropic",
            model="test-model",
            api_key="private-do-not-print",
            api_key_env="ANTHROPIC_API_KEY",
        ),
    )


def test_doctor_success_json_and_replay_deduplication(monkeypatch, tmp_path, capsys):
    replay = tmp_path / "game.aoe2record"
    replay.touch()
    monkeypatch.setattr(doctor, "find_replays", lambda: [replay, replay])
    assert cli.main(["doctor", "--json"]) == 0
    output = capsys.readouterr().out
    assert "private-do-not-print" not in output
    payload = json.loads(output)
    assert payload["ok"] is True
    checks = {c["name"]: c for c in payload["checks"]}
    assert checks["replays"]["message"].startswith("Found 1 replay")
    assert checks["key:chat"]["status"] == "ok"


def test_missing_keys_and_model_fail_with_task_specific_fixes(monkeypatch, capsys):
    calls = []

    def missing_config(*, require_key, task):
        calls.append((require_key, task))
        return SimpleNamespace(
            provider="openai", model="", api_key="", api_key_env="MY_PROVIDER_KEY"
        )

    monkeypatch.setattr(doctor, "load_config", missing_config)
    assert cli.main(["doctor"]) == 1
    output = capsys.readouterr().out
    assert "Set MY_PROVIDER_KEY" in output
    assert "AOE2COACH_CHAT_MODEL" in output
    assert calls == [(False, "analysis"), (False, "chat"), (False, "trends"), (False, "detect")]


def test_parser_conflict_does_not_attempt_import(monkeypatch):
    monkeypatch.setattr(doctor, "_installed", lambda _: True)

    def unexpected():
        raise AssertionError("must report the module collision before importing")

    monkeypatch.setattr(doctor, "_detect_backend", unexpected)
    check = doctor.check_setup()[0]
    assert check.status == "error"
    assert "fresh virtual environment" in check.message


def test_missing_parser_and_optional_packages(monkeypatch):
    def missing():
        raise ValueError("parser unavailable")

    monkeypatch.setattr(doctor, "_detect_backend", missing)
    monkeypatch.setattr(doctor, "_importable", lambda _: False)
    checks = {c.name: c for c in doctor.check_setup()}
    assert checks["parser"].status == "error"
    assert ".[fast]" in checks["parser"].message
    assert checks["sdk:analysis"].status == "error"
    assert checks["web"].status == "warning"
    assert checks["mcp"].status == "warning"


def test_invalid_config_and_replay_errors_do_not_echo_exception_details(monkeypatch, capsys):
    def invalid(**kwargs):
        raise ConfigError("bad setting: private-do-not-print")

    def denied():
        raise PermissionError("private-path-do-not-print")

    monkeypatch.setattr(doctor, "load_config", invalid)
    monkeypatch.setattr(doctor, "find_replays", denied)
    assert cli.main(["doctor"]) == 1
    output = capsys.readouterr().out
    assert "do-not-print" not in output
    assert "AOE2COACH_CHAT_*" in output
    assert "could not be read" in output


def test_doctor_real_config_never_constructs_a_provider_client(monkeypatch):
    import anthropic

    from aoe2coach.config import load_config

    for name in list(os.environ):
        if name.startswith("AOE2COACH_") or name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(name)
    monkeypatch.setattr("aoe2coach.config.load_dotenv", lambda: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "private-do-not-print")
    monkeypatch.setattr(doctor, "load_config", load_config)

    def no_network(*args, **kwargs):
        raise AssertionError("doctor must not create a provider client")

    monkeypatch.setattr(anthropic, "Anthropic", no_network)
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=no_network))
    assert all(c.status != "error" for c in doctor.check_setup())


def test_missing_local_replays_is_only_a_warning():
    checks = {c.name: c for c in doctor.check_setup()}
    assert checks["replays"].status == "warning"
    assert "drag one" in checks["replays"].message
    assert not Path("reports").exists()
