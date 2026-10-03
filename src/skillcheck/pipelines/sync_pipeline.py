"""Manual catalog synchronization pipeline."""

from __future__ import annotations

from pathlib import Path

from skillcheck.catalog.models import SyncSummary


class CatalogNotInitialized(RuntimeError):
    """Raised when synchronization is requested before catalog initialization."""


class SyncPipeline:
    def __init__(self, config, repository, reconciler) -> None:
        self.config = config
        self.repository = repository
        self.reconciler = reconciler

    def run(self, *, paths: list[Path] | None = None) -> SyncSummary:
        if not self.config.catalog.initialized:
            raise CatalogNotInitialized("请先运行 skillcheck init")
        roots = self.repository.list_roots()
        # Typer's legacy list argument yields [] when omitted; treat that as a
        # full reconciliation rather than an empty incremental change set.
        return self.reconciler.reconcile(roots, changed_paths=paths or None)
