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


def test_each_mcp_tool_syncs_runtime_before_query() -> None:
    calls: list[str] = []
    repositories = SimpleNamespace(
        reports=SimpleNamespace(latest_summary=dict, get_public=lambda report_id: {}),
        groups=SimpleNamespace(list_public=lambda **kwargs: []),
    )
    runtime = SimpleNamespace(before_query=lambda: calls.append("before_query"))
    server = create_server(SkillcheckQueries(repositories), runtime=runtime)

    asyncio.run(server.call_tool("skillcheck_summary", {}))
    asyncio.run(server.call_tool("skillcheck_groups", {}))
    asyncio.run(server.call_tool("skillcheck_report", {"report_id": "report-1"}))

    assert calls == ["before_query", "before_query", "before_query"]


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
    monkeypatch.setattr("skillcheck.mcp.server.create_server", lambda _, runtime: Server())

    run_stdio(tmp_path / "config.yaml")

    assert calls == ["start", "stdio", "stop"]


def test_stdio_passes_not_initialized_runtime_to_server(monkeypatch, tmp_path) -> None:
    observed = []
    status = SimpleNamespace(state="not_initialized")

    class Runtime:
        def start(self):
            return status

        def stop(self):
            pass

    class Server:
        def run(self, transport):
            pass

    config = SimpleNamespace(reports_path=tmp_path / "reports")
    monkeypatch.setattr("skillcheck.mcp.server.load_or_create_config", lambda _: config)
    monkeypatch.setattr("skillcheck.mcp.server.McpRuntime", lambda value: Runtime())
    monkeypatch.setattr(
        "skillcheck.mcp.server.create_server",
        lambda _, runtime: observed.append(runtime) or Server(),
    )

    run_stdio(tmp_path / "config.yaml")

    assert len(observed) == 1
    assert observed[0].start() is status
