from __future__ import annotations

from pathlib import Path

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.models import RootScope, SyncSummary
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.config.models import AppConfig
from skillcheck.mcp.runtime import McpRuntime


class RecordingReconciler:
    def __init__(self) -> None:
        self.calls: list[list[Path] | None] = []

    def reconcile(self, roots, changed_paths=None) -> SyncSummary:
        self.calls.append(changed_paths)
        return SyncSummary(revision=f"sync-{len(self.calls)}")


class RecordingWatcher:
    def __init__(self, roots, on_changes, **kwargs) -> None:
        self.roots = roots
        self.on_changes = on_changes
        self.warning = None
        self.running = False
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True
        self.running = True

    def stop(self) -> None:
        self.stopped = True
        self.running = False


class FailingWatcher(RecordingWatcher):
    def start(self) -> None:
        self.warning = "watch unavailable"


def _config(tmp_path: Path, *, initialized: bool = True) -> AppConfig:
    config = AppConfig.default(home=tmp_path / "home")
    config.index_path = tmp_path / "catalog.db"
    config.catalog.initialized = initialized
    return config


def test_runtime_reconciles_before_first_query_and_stops_watcher(tmp_path: Path) -> None:
    config = _config(tmp_path)
    database = CatalogDatabase(config.index_path)
    database.initialize()
    reconciler = RecordingReconciler()
    runtime = McpRuntime(
        config,
        CatalogRepository(database),
        reconciler,
        project_path=tmp_path,
        watcher_factory=RecordingWatcher,
    )

    runtime.start()
    runtime.stop()

    assert reconciler.calls == [None]
    assert runtime.watcher is not None
    assert runtime.watcher.started is True
    assert runtime.watcher.stopped is True


def test_runtime_registers_new_project_roots_on_connection(tmp_path: Path) -> None:
    project = tmp_path / "project"
    skills = project / ".codex" / "skills"
    skills.mkdir(parents=True)
    config = _config(tmp_path)
    database = CatalogDatabase(config.index_path)
    database.initialize()
    runtime = McpRuntime(
        config,
        CatalogRepository(database),
        RecordingReconciler(),
        home=tmp_path / "home",
        project_path=project,
        watcher_factory=RecordingWatcher,
    )

    runtime.start()
    root = next(root for root in runtime.repository.list_roots() if root.path == skills.resolve())

    assert root.scope is RootScope.PROJECT
    assert root.project_path == project.resolve()
    assert runtime.status().project_roots_added == 1


def test_pending_change_marks_related_evidence_stale_and_syncs_before_query(tmp_path: Path) -> None:
    config = _config(tmp_path)
    database = CatalogDatabase(config.index_path)
    database.initialize()
    reconciler = RecordingReconciler()
    runtime = McpRuntime(
        config,
        CatalogRepository(database),
        reconciler,
        project_path=tmp_path,
        watcher_factory=RecordingWatcher,
    )
    path = tmp_path / "skills" / "example" / "SKILL.md"
    runtime.start()
    runtime._on_changes({path})

    assert runtime.is_stale([path]) is True
    runtime.before_query()
    assert runtime.is_stale([path]) is False
    assert reconciler.calls == [None, [path.resolve()]]


def test_runtime_does_not_create_database_before_init(tmp_path: Path) -> None:
    config = _config(tmp_path, initialized=False)
    runtime = McpRuntime(config, project_path=tmp_path, watcher_factory=RecordingWatcher)

    runtime.start()

    assert not config.index_path.exists()
    assert runtime.status().state == "not_initialized"


def test_runtime_reports_watcher_failure_as_degraded(tmp_path: Path) -> None:
    config = _config(tmp_path)
    database = CatalogDatabase(config.index_path)
    database.initialize()
    runtime = McpRuntime(
        config,
        CatalogRepository(database),
        RecordingReconciler(),
        project_path=tmp_path,
        watcher_factory=FailingWatcher,
    )

    status = runtime.start()

    assert status.state == "degraded"
    assert status.warnings == ["watch unavailable"]
