"""Application factories for the v0.4 local catalog commands."""

from __future__ import annotations

from pathlib import Path

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.reconcile import CatalogReconciler
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.config import load_or_create_config
from skillcheck.embeddings import backend_from_config
from skillcheck.governance.analyzer import GovernanceAnalyzer
from skillcheck.installation.executor import InstallationExecutor
from skillcheck.installation.planner import InstallationPlanner
from skillcheck.pipelines.add_pipeline import AddPipeline
from skillcheck.pipelines.scan_pipeline import ScanPipeline
from skillcheck.pipelines.sync_pipeline import SyncPipeline
from skillcheck.reports import ReportWriter


def build_scan_pipeline(config_path: Path | str | None = None) -> ScanPipeline:
    config = load_or_create_config(config_path)
    database = CatalogDatabase(config.index_path)
    if config.catalog.initialized:
        database.initialize()
    repository = CatalogRepository(database)
    reconciler = CatalogReconciler(repository, embedding=backend_from_config(config.embedding))
    return ScanPipeline(
        SyncPipeline(config, repository, reconciler),
        GovernanceAnalyzer(repository),
        ReportWriter(config.reports_path),
    )


def build_add_pipeline(config_path: Path | str | None = None) -> AddPipeline:
    config = load_or_create_config(config_path)
    database = CatalogDatabase(config.index_path)
    if not config.catalog.initialized:
        raise ValueError("请先运行 skillcheck init")
    database.initialize()
    repository = CatalogRepository(database)
    pipeline = AddPipeline(
        governance=GovernanceAnalyzer(repository, staging_root=config.staging_path),
        planner=InstallationPlanner(staging_parent=config.staging_path),
        executor=InstallationExecutor(),
    )
    pipeline.config = config
    return pipeline
