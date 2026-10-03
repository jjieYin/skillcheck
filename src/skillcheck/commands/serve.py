"""Start the Agent-native Skillcheck MCP stdio service."""

from __future__ import annotations

from pathlib import Path

import typer


def register(app: typer.Typer) -> None:
    @app.command("serve")
    def serve(
        mcp: bool = typer.Option(False, "--mcp", help="以 MCP stdio 模式运行"),
        config: Path = typer.Option(None, "--config"),
    ) -> None:
        if not mcp:
            raise typer.BadParameter("当前仅支持 skillcheck serve --mcp")
        from skillcheck.mcp.server import run_stdio

        run_stdio(config)
