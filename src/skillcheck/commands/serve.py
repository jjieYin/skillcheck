"""Start the read-only MCP stdio service."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer


def register(app: typer.Typer) -> None:
    @app.command("serve")
    def serve(
        mcp: Annotated[bool, typer.Option("--mcp", help="以 MCP stdio 模式运行")],
        config: Annotated[Path | None, typer.Option("--config")] = None,
    ) -> None:
        if not mcp:
            raise typer.BadParameter("当前仅支持 skillcheck serve --mcp")
        from skillcheck.mcp.server import run_stdio

        run_stdio(config)

