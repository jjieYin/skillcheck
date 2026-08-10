from __future__ import annotations

import asyncio
from types import SimpleNamespace

from skillcheck.mcp.server import TOOL_NAMES, create_server, run_stdio
from skillcheck.mcp.tools import SkillcheckQueries


def test_mcp_exposes_only_read_only_tools() -> None:
    assert TOOL_NAMES == {"skillcheck_summary", "skillcheck_groups", "skillcheck_report"}
    assert not any(word in name for name in TOOL_NAMES for word in ("install", "delete", "write", "save"))


def test_server_registers_exact_tool_names() -> None:
    repositories = SimpleNamespace(
        reports=SimpleNamespace(latest_summary=dict, get_public=lambda report_id: {}),
        groups=SimpleNamespace(list_public=lambda **kwargs: []),
    )
    server = create_server(SkillcheckQueries(repositories))
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == TOOL_NAMES


def test_stdio_starts_and_stops_catalog_runtime(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    class Runtime:
        def start(self):
            calls.append("start")

        def stop(self):
            calls.append("stop")

    class Server:
        def run(self, transport):
            calls.append(transport)

    config = SimpleNamespace(reports_path=tmp_path / "reports")
    monkeypatch.setattr("skillcheck.mcp.server.load_or_create_config", lambda _: config)
    monkeypatch.setattr("skillcheck.mcp.server.McpRuntime", lambda value: Runtime())
    monkeypatch.setattr("skillcheck.mcp.server.create_server", lambda _: Server())

    run_stdio(tmp_path / "config.yaml")

    assert calls == ["start", "stdio", "stop"]
