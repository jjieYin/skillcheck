"""MCP stdio server exposing exactly three read-only tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from skillcheck.config import load_or_create_config
from skillcheck.mcp.instructions import MCP_INSTRUCTIONS
from skillcheck.mcp.repositories import FileRepositories
from skillcheck.mcp.runtime import McpRuntime
from skillcheck.mcp.tools import SkillcheckQueries

TOOL_NAMES = {"skillcheck_summary", "skillcheck_groups", "skillcheck_report"}


def create_server(
    queries: SkillcheckQueries | None = None, runtime: McpRuntime | None = None
) -> FastMCP:
    if queries is None:
        config = load_or_create_config()
        queries = SkillcheckQueries(FileRepositories(config.reports_path))
    server = FastMCP("skillcheck", instructions=MCP_INSTRUCTIONS, log_level="ERROR")

    @server.tool(name="skillcheck_summary", description="读取最近一次 Skill 治理摘要")
    def skillcheck_summary() -> dict[str, object]:
        if runtime is not None:
            status = runtime.before_query()
            if getattr(status, "state", None) == "not_initialized":
                return status.model_dump(mode="json")
        return queries.summary()

    @server.tool(name="skillcheck_groups", description="读取重复、重叠和冲突分组的脱敏证据")
    def skillcheck_groups(relation: str | None = None, limit: int = 20) -> Any:
        if runtime is not None:
            status = runtime.before_query()
            if getattr(status, "state", None) == "not_initialized":
                return status.model_dump(mode="json")
        return queries.groups(relation=relation, limit=limit)

    @server.tool(name="skillcheck_report", description="读取指定报告的脱敏结果")
    def skillcheck_report(report_id: str) -> dict[str, object]:
        if runtime is not None:
            status = runtime.before_query()
            if getattr(status, "state", None) == "not_initialized":
                return status.model_dump(mode="json")
        return queries.report(report_id)

    return server


def run_stdio(config_path: Path | str | None = None) -> None:
    config = load_or_create_config(config_path)
    queries = SkillcheckQueries(FileRepositories(config.reports_path))
    runtime = McpRuntime(config)
    runtime.start()
    try:
        create_server(queries, runtime=runtime).run("stdio")
    finally:
        runtime.stop()
