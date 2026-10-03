"""Application factories for the v0.4 local catalog commands."""

from __future__ import annotations

from pathlib import Path

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.reconcile import CatalogReconciler
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.config import load_config
from skillcheck.embeddings import backend_for_config
from skillcheck.governance.analyzer import GovernanceAnalyzer
from skillcheck.governance.policy import GovernancePolicy
from skillcheck.installation.executor import InstallationExecutor
from skillcheck.installation.planner import InstallationPlanner
from skillcheck.pipelines.add_pipeline import AddPipeline
from skillcheck.pipelines.scan_pipeline import ScanPipeline
from skillcheck.pipelines.sync_pipeline import SyncPipeline
from skillcheck.reports import ReportWriter
from skillcheck.vectorization import VectorizationService


def build_scan_pipeline(config_path: Path | str | None = None) -> ScanPipeline:
    config = load_config(config_path)
    database = CatalogDatabase(config.catalog.database_path)
    if config.catalog.initialized:
        database.initialize()
    repository = CatalogRepository(database)
    backend = backend_for_config(config.embedding)
    reconciler = CatalogReconciler(repository, embedding=backend)
    return ScanPipeline(
        SyncPipeline(config, repository, reconciler),
        GovernanceAnalyzer(
            repository,
            policy=GovernancePolicy.from_config(config, project_path=Path.cwd()),
            vectorization=VectorizationService(repository, backend),
        ),
        ReportWriter(config.reports.directory),
    )


def build_add_pipeline(config_path: Path | str | None = None) -> AddPipeline:
    config = load_config(config_path)
    database = CatalogDatabase(config.catalog.database_path)
    if not config.catalog.initialized:
        raise ValueError("请先运行 skillcheck init")
    database.initialize()
    repository = CatalogRepository(database)
    backend = backend_for_config(config.embedding)
    pipeline = AddPipeline(
        governance=GovernanceAnalyzer(
            repository,
            staging_root=config.catalog.staging_path,
            policy=GovernancePolicy.from_config(config),
            vectorization=VectorizationService(repository, backend),
        ),
        planner=InstallationPlanner(staging_parent=config.catalog.staging_path),
        executor=InstallationExecutor(),
    )
    pipeline.config = config
    return pipeline
