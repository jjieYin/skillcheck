"""Manual incremental catalog synchronization command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.reconcile import CatalogReconciler
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.config import load_config
from skillcheck.embeddings import backend_from_config
from skillcheck.pipelines.sync_pipeline import SyncPipeline


def build_sync_pipeline(config_path: Path | None) -> SyncPipeline:
    config = load_config(config_path, create=False)
    repository = CatalogRepository(CatalogDatabase(config.catalog.database_path))
    return SyncPipeline(config, repository, CatalogReconciler(repository, embedding=backend_from_config(config.embedding)))


def register(app: typer.Typer) -> None:
    @app.command("sync")
    def sync(
        paths: Annotated[list[Path] | None, typer.Argument()] = None,
        config: Annotated[Path | None, typer.Option("--config")] = None,
        as_json: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        summary = build_sync_pipeline(config).run(paths=paths)
        if as_json:
            typer.echo(summary.model_dump_json())
            return
        typer.echo(f"revision: {summary.revision}")
        typer.echo(f"added: {summary.added}")
        typer.echo(f"updated: {summary.updated}")
        typer.echo(f"removed: {summary.removed}")
        typer.echo(f"invalid: {summary.invalid}")
