"""Initialize the local v0.4 Skill catalog."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from pydantic import BaseModel

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.discovery import discover_library_roots
from skillcheck.catalog.models import LibraryRoot, SyncSummary
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.config.loader import save_config
from skillcheck.config.models import AppConfig


class InitPreview(BaseModel):
    roots: list[LibraryRoot]
    database_path: Path


class InitResult(BaseModel):
    changed: bool
    sync: SyncSummary


class InitPipeline:
    def __init__(
        self,
        config: AppConfig,
        config_path: Path | str,
        *,
        home: Path | str | None = None,
        project: Path | str | None = None,
        reconcile: Callable[[list[LibraryRoot]], SyncSummary] | None = None,
    ) -> None:
        self.config = config
        self.config_path = Path(config_path).expanduser()
        self.home = Path.home() if home is None else Path(home).expanduser()
        self.project = Path.cwd() if project is None else Path(project).expanduser()
        self._reconcile = reconcile or _initial_reconcile

    def discover(self, extra_paths: Iterable[Path | str]) -> list[LibraryRoot]:
        return discover_library_roots(self.home, self.project, extra_paths)

    def preview(self, roots: Iterable[LibraryRoot]) -> InitPreview:
        return InitPreview(
            roots=sorted(roots, key=lambda root: str(root.path)),
            database_path=self.config.index_path,
        )

    def apply(self, preview: InitPreview, *, confirmed: bool) -> InitResult:
        if not confirmed:
            return InitResult(changed=False, sync=SyncSummary(revision="cancelled"))

        database = CatalogDatabase(preview.database_path)
        database.initialize()
        repository = CatalogRepository(database)
        for root in preview.roots:
            repository.upsert_root(root)
        sync = self._reconcile(preview.roots)
        self.config.catalog.initialized = True
        self.config.catalog.roots = [root.path for root in preview.roots]
        self.config.schema_version = 4
        save_config(self.config_path, self.config)
        return InitResult(changed=True, sync=sync)


def _initial_reconcile(roots: list[LibraryRoot]) -> SyncSummary:
    """Temporary Task 3 seam; Task 4 replaces it with the catalog reconciler."""
    del roots
    return SyncSummary(revision="initial")
