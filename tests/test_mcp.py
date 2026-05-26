"""Smoke test for the MCP server. Skips if the optional `mcp` extra isn't installed."""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("mcp.server.fastmcp")

from aoe2coach import mcp_server  # noqa: E402


def test_server_registers_tools_and_prompts():
    assert mcp_server.mcp.name == "aoe2coach"
    tools = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    prompts = {p.name for p in asyncio.run(mcp_server.mcp.list_prompts())}
    assert {"list_replays", "replay_metrics", "replay_trends"} <= tools
    assert {"coach", "coach_trends"} <= prompts


def test_replay_metrics_error_is_graceful():
    out = json.loads(mcp_server.replay_metrics("/nonexistent/none.aoe2record"))
    assert "error" in out
