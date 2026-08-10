from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from skillcheck.config import load_or_create_config
from skillcheck.pipelines.scan_pipeline import ReviewMode, ScanScope


def build_scan_pipeline(config: Path | None):
    from skillcheck.app.context import build_scan_pipeline as factory

    return factory(config)


def register(app: typer.Typer) -> None:
    @app.command("scan")
    def scan(
        path: Annotated[Path | None, typer.Argument()] = None,
        review: Annotated[ReviewMode | None, typer.Option("--review")] = None,
        no_interactive: Annotated[bool, typer.Option("--no-interactive")] = False,
        config: Annotated[Path | None, typer.Option("--config")] = None,
        as_json: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        pipeline = build_scan_pipeline(config)
        configuration = getattr(pipeline, "config", None)
        if configuration is None:
            configuration = load_or_create_config(config)
        mode = configuration.effective_review_mode(
            interactive=not no_interactive and sys.stdin.isatty(),
            cli_value=review.value if review else None,
        )
        outcome = pipeline.run(
            ScanScope(paths=[str(path)] if path else []),
            ReviewMode(mode),
        )
        if as_json:
            typer.echo(outcome.report.json_path.read_text(encoding="utf-8"))
        else:
            typer.echo(f"扫描完成：{outcome.skill_count} 个 Skill")
            typer.echo(f"报告：{outcome.report.markdown}")
