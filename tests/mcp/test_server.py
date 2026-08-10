from __future__ import annotations

import asyncio
from types import SimpleNamespace

from skillcheck.mcp.server import TOOL_NAMES, create_server
from skillcheck.mcp.tools import SkillcheckQueries


def test_mcp_exposes_only_read_only_tools() -> None:
    assert TOOL_NAMES == {"skillcheck_summary", "skillcheck_groups", "skillcheck_report"}
    assert not any(word in name for name in TOOL_NAMES for word in ("install", "delete", "write", "save"))


def test_server_registers_exact_tool_names() -> None:
    repositories = SimpleNamespace(
        reports=SimpleNamespace(latest_summary=lambda: {}, get_public=lambda report_id: {}),
        groups=SimpleNamespace(list_public=lambda **kwargs: []),
    )
    server = create_server(SkillcheckQueries(repositories))
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == TOOL_NAMES

