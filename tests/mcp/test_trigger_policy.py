from __future__ import annotations

from skillcheck.mcp.instructions import MCP_INSTRUCTIONS


def test_instructions_are_conditional_and_exclude_ordinary_work() -> None:
    assert "Only use Skillcheck when" in MCP_INSTRUCTIONS
    assert "Do not call Skillcheck for ordinary coding" in MCP_INSTRUCTIONS
    assert "If no candidate groups are returned" in MCP_INSTRUCTIONS
    assert "Do not call skillcheck_evidence" in MCP_INSTRUCTIONS
