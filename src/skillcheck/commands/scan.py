"""Local-only CLI fallback scan."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from skillcheck.pipelines.sync_pipeline import CatalogNotInitialized


def build_scan_pipeline(config: Path | None):
    from skillcheck.app.context import build_scan_pipeline as factory

    return factory(config)


def register(app: typer.Typer) -> None:
    @app.command("scan")
    def scan(
        path: Path = typer.Argument(None),
        config: Path = typer.Option(None, "--config"),
        as_json: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            result = build_scan_pipeline(config).run([path] if path is not None else [])
        except CatalogNotInitialized as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(code=2) from error
        if as_json:
            typer.echo(json.dumps(result.json_payload(), ensure_ascii=False, indent=2))
            return
        typer.echo(f"本地扫描完成：{result.skill_count} 个 Skill")
        typer.echo(f"报告：{result.report.markdown}")
