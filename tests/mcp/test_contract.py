from __future__ import annotations

import asyncio

from skillcheck.mcp.server import TOOL_NAMES, create_server

EXPECTED_TOOLS = {
    "skillcheck_analyze",
    "skillcheck_evidence",
    "skillcheck_save_review",
    "skillcheck_save_sync_group",
}


def test_contract_exposes_no_legacy_governance_tools() -> None:
    assert TOOL_NAMES == EXPECTED_TOOLS
    tools = type(
        "Tools",
        (),
        {
            "analyze": lambda *_: {},
            "evidence": lambda *_: {},
            "save_review": lambda *_: {},
            "save_sync_group": lambda *_: {},
        },
    )()
    server = create_server(tools)
    assert {tool.name for tool in asyncio.run(server.list_tools())} == EXPECTED_TOOLS
