"""MCP stdio server exposing exactly three read-only tools."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from skillcheck.config import load_or_create_config
from skillcheck.mcp.instructions import MCP_INSTRUCTIONS
from skillcheck.mcp.repositories import FileRepositories
from skillcheck.mcp.tools import SkillcheckQueries


TOOL_NAMES = {"skillcheck_summary", "skillcheck_groups", "skillcheck_report"}


def create_server(queries: SkillcheckQueries | None = None) -> FastMCP:
    if queries is None:
        config = load_or_create_config()
        queries = SkillcheckQueries(FileRepositories(config.reports_path))
    server = FastMCP("skillcheck", instructions=MCP_INSTRUCTIONS, log_level="ERROR")

    @server.tool(name="skillcheck_summary", description="读取最近一次 Skill 治理摘要")
    def skillcheck_summary() -> dict[str, object]:
        return queries.summary()

    @server.tool(name="skillcheck_groups", description="读取重复、重叠和冲突分组的脱敏证据")
    def skillcheck_groups(relation: str | None = None, limit: int = 20) -> list[dict[str, object]]:
        return queries.groups(relation=relation, limit=limit)

    @server.tool(name="skillcheck_report", description="读取指定报告的脱敏结果")
    def skillcheck_report(report_id: str) -> dict[str, object]:
        return queries.report(report_id)

    return server


def run_stdio(config_path: Path | str | None = None) -> None:
    queries = None
    if config_path is not None:
        config = load_or_create_config(config_path)
        queries = SkillcheckQueries(FileRepositories(config.reports_path))
    create_server(queries).run("stdio")

