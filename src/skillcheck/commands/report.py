from __future__ import annotations

from pathlib import Path

import typer

from skillcheck.config import load_config
from skillcheck.reports import ReportWriter


def register(app: typer.Typer) -> None:
    @app.command("report")
    def report(
        action: str = typer.Argument(..., help="latest、show 或 open"),
        report_id: str = typer.Argument(None),
        config: Path = typer.Option(None, "--config"),
        as_json: bool = typer.Option(False, "--json"),
    ) -> None:
        loaded = load_config(config)
        writer = ReportWriter(loaded.reports.directory)
        if action == "latest":
            paths = writer.latest()
            if paths is None:
                raise typer.BadParameter("没有报告")
        elif action in {"show", "open"} and report_id:
            paths = writer.find(report_id)
        else:
            raise typer.BadParameter("用法：skillcheck report latest|show REPORT_ID|open REPORT_ID")
        if action == "open":
            typer.echo(str(paths.markdown))
        elif as_json:
            typer.echo(paths.json.read_text(encoding="utf-8"))
        else:
            typer.echo(paths.markdown.read_text(encoding="utf-8"))
