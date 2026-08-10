"""Cursor JSON MCP target adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from skillcheck.targets._mcp import McpTarget
from skillcheck.targets.base import AgentId


class CursorTarget(McpTarget):
    agent = AgentId.CURSOR
    format = "json"

    def __init__(
        self,
        config_path: Path | str | None = None,
        *,
        global_config: Path | str | None = None,
        project_config: Path | str | None = None,
        launcher: str = "skillcheck",
        cli_search_path: Iterable[Path] | None = None,
        skill_paths: Iterable[Path] | None = None,
    ) -> None:
        effective_global = global_config or config_path or Path.home() / ".cursor" / "mcp.json"
        super().__init__(
            global_config=effective_global,
            project_config=project_config,
            launcher=launcher,
            cli_search_path=cli_search_path,
            skill_paths=skill_paths,
        )


CursorAdapter = CursorTarget
