"""MCP stdio server exposing the CodeGraph-mode governance contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from skillcheck.config import load_config
from skillcheck.mcp.instructions import MCP_INSTRUCTIONS
from skillcheck.mcp.runtime import McpRuntime
from skillcheck.mcp.tools import SkillcheckMcpTools

TOOL_NAMES = {
    "skillcheck_analyze",
    "skillcheck_evidence",
    "skillcheck_save_review",
}


def create_server(tools: SkillcheckMcpTools) -> FastMCP:
    """Create a server with only Agent-native governance tools."""
    server = FastMCP("skillcheck", instructions=MCP_INSTRUCTIONS, log_level="ERROR")

    @server.tool(name="skillcheck_analyze", description="Analyze a local Skill library or incoming source.")
    def skillcheck_analyze(
        mode: str,
        source: str | None = None,
        scope: str = "all",
        limit: int = 20,
    ) -> dict[str, object]:
        return tools.analyze(mode, source, scope, limit)

    @server.tool(name="skillcheck_evidence", description="Read bounded, redacted evidence for one candidate group.")
    def skillcheck_evidence(
        run_id: str,
        group_id: str,
        page: int = 0,
        include_body: bool = False,
    ) -> dict[str, object]:
        return tools.evidence(run_id, group_id, page, include_body)

    @server.tool(name="skillcheck_save_review", description="Save the Agent's explicit governance decisions as a report.")
    def skillcheck_save_review(run_id: str, decisions: list[dict[str, Any]]) -> dict[str, object]:
        return tools.save_review(run_id, decisions)

    return server


def build_runtime(config_path: Path | str | None = None) -> McpRuntime:
    return McpRuntime(load_config(config_path))


def run_stdio(config_path: Path | str | None = None) -> None:
    runtime = build_runtime(config_path)
    runtime.start()
    try:
        create_server(SkillcheckMcpTools(runtime)).run("stdio")
    finally:
        runtime.stop()
