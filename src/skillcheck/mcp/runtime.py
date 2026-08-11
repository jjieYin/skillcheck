"""MCP-session catalog lifecycle and stale-state coordination."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from threading import Lock, RLock
from typing import Literal

from pydantic import BaseModel, Field

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.discovery import discover_library_roots
from skillcheck.catalog.models import LibraryRoot, RootScope
from skillcheck.catalog.reconcile import CatalogReconciler
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.catalog.watcher import CatalogWatcher
from skillcheck.config.models import AppConfig


class RuntimeStatus(BaseModel):
    state: Literal["ready", "not_initialized", "degraded"]
    initialized: bool
    watching: bool
    revision: str | None
    pending_count: int
    project_roots_added: int = 0
    warnings: list[str] = Field(default_factory=list)


class McpRuntime:
    """Keep a pre-initialized catalog fresh for the lifetime of one MCP process."""

    def __init__(
        self,
        config: AppConfig,
        repository: CatalogRepository | None = None,
        reconciler: CatalogReconciler | None = None,
        *,
        home: Path | str | None = None,
        project_path: Path | str | None = None,
        watcher_factory: Callable[..., CatalogWatcher] = CatalogWatcher,
    ) -> None:
        self.config = config
        self.home = Path.home() if home is None else Path(home).expanduser()
        self._project_path = Path.cwd() if project_path is None else Path(project_path).expanduser()
        self._project_path_explicit = project_path is not None
        self.repository = repository
        self.reconciler = reconciler
        self.watcher_factory = watcher_factory
        self.watcher: CatalogWatcher | None = None
        self.pending: set[Path] = set()
        self._pending_lock = Lock()
        self._query_lock = Lock()
        self._lifecycle_lock = RLock()
        self._revision: str | None = None
        self._warnings: list[str] = []
        self._project_roots_added = 0
        self._started = False

    @property
    def project_path(self) -> Path:
        return self._project_path

    @project_path.setter
    def project_path(self, value: Path | str) -> None:
        self._project_path = Path(value).expanduser()
        self._project_path_explicit = True

    def start(self) -> RuntimeStatus:
        with self._lifecycle_lock:
            if self._started:
                return self.status()
            self._started = True
            if not self.config.catalog.initialized:
                return self.status()
            if not self._project_path_explicit:
                self._project_path = Path.cwd()
            self._ensure_catalog()
            assert self.repository is not None
            assert self.reconciler is not None
            roots = self._register_project_roots()
            summary = self.reconciler.reconcile(roots)
            self._revision = summary.revision
            self._warnings.extend(summary.warnings)
            self.watcher = self.watcher_factory(
                [root.path for root in roots if root.enabled],
                self._on_changes,
                debounce_ms=self.config.catalog.debounce_ms,
            )
            if getattr(self.watcher, "available", True):
                self.watcher.start()
            else:
                self.watcher.warning = "watchfiles is unavailable"
            if self.watcher.warning:
                self._warnings.append(self.watcher.warning)
            return self.status()

    def stop(self) -> None:
        with self._lifecycle_lock:
            if self.watcher is not None:
                self.watcher.stop()

    def before_query(self) -> RuntimeStatus:
        with self._query_lock:
            if not self.config.catalog.initialized:
                return self.status()
            with self._pending_lock:
                changed_paths = sorted(self.pending)
                self.pending.clear()
            if changed_paths and self.reconciler is not None and self.repository is not None:
                summary = self.reconciler.reconcile(
                    self.repository.list_roots(), changed_paths=changed_paths
                )
                self._revision = summary.revision
                self._warnings.extend(summary.warnings)
            return self.status()

    def is_stale(self, paths: list[Path | str]) -> bool:
        evidence_paths = [self._normalized_path(path) for path in paths]
        pending = self.pending_paths()
        return any(self._overlaps(change, evidence) for change in pending for evidence in evidence_paths)

    def pending_paths(self) -> set[Path]:
        """Return a snapshot of pending normalized paths without consuming them."""
        with self._pending_lock:
            return set(self.pending)

    def status(self) -> RuntimeStatus:
        warning = self.watcher.warning if self.watcher is not None else None
        warnings = [*self._warnings, *([warning] if warning and warning not in self._warnings else [])]
        if self.watcher is not None and getattr(self.watcher, "startup_pending", False):
            warnings.append("watcher startup is pending")
        initialized = self.config.catalog.initialized
        watching = bool(self.watcher and self.watcher.running)
        state: Literal["ready", "not_initialized", "degraded"]
        if not initialized:
            state = "not_initialized"
        elif warnings:
            state = "degraded"
        else:
            state = "ready"
        with self._pending_lock:
            pending_count = len(self.pending)
        return RuntimeStatus(
            state=state,
            initialized=initialized,
            watching=watching,
            revision=self._revision,
            pending_count=pending_count,
            project_roots_added=self._project_roots_added,
            warnings=warnings,
        )

    def _ensure_catalog(self) -> None:
        if self.repository is None:
            self.repository = CatalogRepository(CatalogDatabase(self.config.catalog.database_path))
        if self.reconciler is None:
            self.reconciler = CatalogReconciler(self.repository)

    def _register_project_roots(self) -> list[LibraryRoot]:
        assert self.repository is not None
        existing = {self._normalized_path(root.path) for root in self.repository.list_roots()}
        discovered = discover_library_roots(self.home, self.project_path, self.config.catalog.roots)
        for root in discovered:
            if root.scope is RootScope.PROJECT and self._normalized_path(root.path) not in existing:
                self.repository.upsert_root(root)
                existing.add(self._normalized_path(root.path))
                self._project_roots_added += 1
        return self.repository.list_roots()

    def _on_changes(self, paths: set[Path]) -> None:
        with self._pending_lock:
            self.pending.update(self._normalized_path(path) for path in paths)

    @staticmethod
    def _normalized_path(path: Path | str) -> Path:
        return Path(os.path.normcase(str(Path(path).expanduser().resolve(strict=False))))

    @staticmethod
    def _overlaps(first: Path, second: Path) -> bool:
        return first == second or first in second.parents or second in first.parents
