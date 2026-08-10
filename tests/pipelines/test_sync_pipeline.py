from pathlib import Path

import pytest

from skillcheck.catalog.models import LibraryRoot, RootScope, SyncSummary
from skillcheck.config.models import AppConfig
from skillcheck.pipelines.sync_pipeline import CatalogNotInitialized, SyncPipeline


class _Repository:
    def __init__(self, roots: list[LibraryRoot]) -> None:
        self.roots = roots

    def list_roots(self) -> list[LibraryRoot]:
        return self.roots


class _Reconciler:
    def __init__(self) -> None:
        self.calls: list[tuple[list[LibraryRoot], list[Path] | None]] = []

    def reconcile(self, roots, changed_paths=None) -> SyncSummary:
        self.calls.append((roots, changed_paths))
        return SyncSummary(revision="revision-1", updated=1)


def test_sync_requires_catalog_initialization(tmp_path: Path) -> None:
    config = AppConfig.default(tmp_path)
    pipeline = SyncPipeline(config, _Repository([]), _Reconciler())

    with pytest.raises(CatalogNotInitialized, match="skillcheck init"):
        pipeline.run()


def test_sync_reconciles_persisted_roots_and_optional_paths(tmp_path: Path) -> None:
    config = AppConfig.default(tmp_path)
    config.catalog.initialized = True
    root = LibraryRoot(root_id="root-1", path=tmp_path / "skills", provider="codex", scope=RootScope.PROJECT)
    reconciler = _Reconciler()
    pipeline = SyncPipeline(config, _Repository([root]), reconciler)
    changed = root.path / "example" / "SKILL.md"

    summary = pipeline.run(paths=[changed])

    assert summary == SyncSummary(revision="revision-1", updated=1)
    assert reconciler.calls == [([root], [changed])]
