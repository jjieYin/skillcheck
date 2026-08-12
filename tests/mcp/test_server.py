from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from skillcheck.mcp.server import TOOL_NAMES, create_server, run_stdio


def test_mcp_exposes_exactly_four_agent_native_tools() -> None:
    assert TOOL_NAMES == {
        "skillcheck_analyze",
        "skillcheck_evidence",
        "skillcheck_save_review",
        "skillcheck_save_sync_group",
    }


def test_server_registers_exact_tool_names() -> None:
    tools = SimpleNamespace(
        analyze=lambda *args: {},
        evidence=lambda *args: {},
        save_review=lambda *args: {},
        save_sync_group=lambda *args: {},
    )
    server = create_server(tools)

    registered = asyncio.run(server.list_tools())

    assert {tool.name for tool in registered} == TOOL_NAMES


def test_analyze_schema_does_not_expose_a_skill_count_limit() -> None:
    tools = SimpleNamespace(
        analyze=lambda *args: {},
        evidence=lambda *args: {},
        save_review=lambda *args: {},
        save_sync_group=lambda *args: {},
    )
    server = create_server(tools)

    registered = asyncio.run(server.list_tools())
    analyze = next(tool for tool in registered if tool.name == "skillcheck_analyze")

    assert "limit" not in analyze.inputSchema["properties"]


def test_stdio_stops_runtime_when_server_raises(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    class Runtime:
        def start(self):
            calls.append("start")

        def stop(self):
            calls.append("stop")

    class Server:
        def run(self, transport):
            calls.append(transport)
            raise RuntimeError("server stopped unexpectedly")

    config = SimpleNamespace()
    monkeypatch.setattr("skillcheck.mcp.server.load_config", lambda _: config)
    monkeypatch.setattr("skillcheck.mcp.server.McpRuntime", lambda value: Runtime())
    monkeypatch.setattr("skillcheck.mcp.server.SkillcheckMcpTools", lambda value: object())
    monkeypatch.setattr("skillcheck.mcp.server.create_server", lambda value: Server())

    with pytest.raises(RuntimeError, match="unexpectedly"):
        run_stdio(tmp_path / "config.yaml")

    assert calls == ["start", "stdio", "stop"]
