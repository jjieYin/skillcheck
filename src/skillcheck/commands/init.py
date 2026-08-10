"""Confirmation-based local catalog initialization command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from skillcheck.config import app_home, load_config
from skillcheck.pipelines.init_pipeline import InitPipeline


def _config_path(path: Path | None) -> Path:
    return path.expanduser() if path is not None else app_home() / "config.yaml"


def build_init_pipeline(config_path: Path | None) -> InitPipeline:
    path = _config_path(config_path)
    return InitPipeline(load_config(path, create=False), path)


def register(app: typer.Typer) -> None:
    @app.command("init")
    def init_catalog(
        paths: Annotated[list[Path] | None, typer.Argument()] = None,
        yes: Annotated[bool, typer.Option("--yes")] = False,
        config: Annotated[Path | None, typer.Option("--config")] = None,
    ) -> None:
        pipeline = build_init_pipeline(config)
        preview = pipeline.preview(pipeline.discover(paths or []))
        for root in preview.roots:
            typer.echo(f"- {root.provider} {root.scope.value}: {root.path}")
        confirmed = yes or typer.confirm("Create the Skills catalog from these roots?")
        result = pipeline.apply(preview, confirmed=confirmed)
        if not result.changed:
            typer.echo("Cancelled; no configuration or catalog changes were made.")
            return
        typer.echo(
            "Initialized: "
            f"added {result.sync.added}, updated {result.sync.updated}, "
            f"invalid {result.sync.invalid}"
        )
