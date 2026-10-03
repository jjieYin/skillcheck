"""Manual incremental catalog synchronization command."""

from __future__ import annotations

from pathlib import Path

import typer

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.reconcile import CatalogReconciler
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.config import load_config
from skillcheck.embeddings import backend_for_config
from skillcheck.pipelines.sync_pipeline import SyncPipeline


def build_sync_pipeline(config_path: Path | None) -> SyncPipeline:
    config = load_config(config_path, create=False)
    repository = CatalogRepository(CatalogDatabase(config.catalog.database_path))
    return SyncPipeline(config, repository, CatalogReconciler(repository, embedding=backend_for_config(config.embedding)))


def register(app: typer.Typer) -> None:
    @app.command("sync")
    def sync(
        paths: list[Path] = typer.Argument(None),
        config: Path = typer.Option(None, "--config"),
        as_json: bool = typer.Option(False, "--json"),
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
