"""Bounded v0.4 diagnostics and explicitly confirmed repairs."""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from skillcheck.catalog.database import CatalogDatabase


class CheckStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


class DoctorCheck(BaseModel):
    code: str
    status: CheckStatus
    message: str
    remediation: str | None = None
    sensitive: bool = False


class DoctorReport(BaseModel):
    checks: list[DoctorCheck] = Field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 2 if any(item.status is CheckStatus.ERROR for item in self.checks) else 1 if any(item.status is CheckStatus.WARNING for item in self.checks) else 0


class FixPlan(BaseModel):
    actions: list[str] = Field(default_factory=list)


REQUIRED_CODES = (
    "runtime.version", "path.shadowing", "config.v4", "catalog.initialized", "catalog.integrity",
    "catalog.sync", "targets.detect", "targets.mcp", "targets.instructions", "mcp.handshake",
    "watcher.available", "reports.permissions",
)


class Doctor:
    def __init__(self, context: Any) -> None:
        self.context = context

    def run(self, *, fix: bool = False) -> DoctorReport:
        del fix
        return DoctorReport(checks=[
            self._runtime(), self._path_shadowing(), self._config_v4(), self._catalog_initialized(),
            self._catalog_integrity(), self._catalog_sync(), self._targets_detect(), self._targets_mcp(),
            self._targets_instructions(), self._mcp_handshake(), self._watcher_available(), self._reports_permissions(),
        ])

    def plan(self, report: DoctorReport) -> FixPlan:
        actions: list[str] = []
        codes = {item.code: item for item in report.checks}
        if any(codes[name].status is not CheckStatus.OK for name in ("targets.mcp", "targets.instructions", "mcp.handshake")):
            actions.append("rewrite_skillcheck_integration")
        if codes["catalog.initialized"].status is CheckStatus.WARNING:
            actions.append("initialize_empty_catalog")
        return FixPlan(actions=actions)

    def apply(self, plan: FixPlan) -> list[str]:
        completed: list[str] = []
        for action in plan.actions:
            if action == "rewrite_skillcheck_integration":
                hook = getattr(self.context, "rewrite_skillcheck_integration", None)
                if callable(hook):
                    hook()
                    completed.append(action)
            elif action == "initialize_empty_catalog":
                hook = getattr(self.context, "initialize_empty_catalog", None)
                if callable(hook):
                    hook()
                else:
                    CatalogDatabase(self.context.index_path).initialize()
                completed.append(action)
        return completed

    def _check(self, code: str, ok: bool, message: str, remediation: str | None = None, *, error: bool = False) -> DoctorCheck:
        return DoctorCheck(code=code, status=CheckStatus.OK if ok else CheckStatus.ERROR if error else CheckStatus.WARNING, message=message, remediation=None if ok else remediation)

    def _runtime(self):
        version = getattr(self.context, "python_version", sys.version_info[:3])
        return self._check("runtime.version", tuple(version) >= (3, 11), "Python runtime is supported", "Install Python 3.11 or newer.", error=True)

    def _path_shadowing(self):
        shadowed = getattr(self.context, "path_shadowing", None)
        if shadowed is None:
            shadowed = shutil.which("skillcheck") is None
        return self._check("path.shadowing", not shadowed, "Skillcheck launcher is unambiguous", "Reinstall Skillcheck and restart the terminal.")

    def _config_v4(self):
        error = getattr(self.context, "config_error", None)
        config = getattr(self.context, "config", None)
        valid = not error and (config is None or getattr(config, "schema_version", 4) == 4)
        return self._check("config.v4", valid, "v0.4 configuration is valid", "Run skillcheck install to create a new v0.4 configuration.", error=bool(error))

    def _catalog_initialized(self):
        config = getattr(self.context, "config", None)
        initialized = getattr(getattr(config, "catalog", None), "initialized", None)
        if initialized is None:
            initialized = Path(getattr(self.context, "index_path", "index.db")).exists()
        return self._check("catalog.initialized", bool(initialized), "Catalog is initialized", "Run skillcheck init, or use doctor --fix to create an empty catalog.")

    def _catalog_integrity(self):
        path = Path(getattr(self.context, "index_path", "index.db"))
        if not path.exists():
            return self._check("catalog.integrity", True, "No catalog exists yet")
        if path.stat().st_size == 0:
            return self._check(
                "catalog.integrity", False, "Catalog is empty", "Run skillcheck init to create a v0.4 catalog."
            )
        try:
            uri = f"{path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as connection:
                connection.row_factory = sqlite3.Row
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                schema = connection.execute(
                    "SELECT value FROM schema_meta WHERE key = 'schema_version'"
                ).fetchone()
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
                    )
                }
                valid = (
                    integrity == "ok"
                    and schema is not None
                    and schema[0] == "4"
                    and CatalogDatabase._expected_tables() <= tables
                    and CatalogDatabase._has_expected_structure(connection)
                )
        except (sqlite3.Error, OSError):
            valid = False
        return self._check("catalog.integrity", valid, "Catalog integrity is valid", "Keep the existing file for backup, then run skillcheck init again.", error=not valid)

    def _catalog_sync(self):
        warning = getattr(self.context, "catalog_sync_warning", None)
        return self._check("catalog.sync", not warning, "Catalog has no recorded sync warning", "Run skillcheck init again after resolving the reported root issue.")

    def _detections(self):
        registry = getattr(self.context, "registry", None)
        try:
            return [
                item for item in (registry.detect_all() if registry else [])
                if item.cli_path or item.config_path or item.instruction_path or item.skill_paths
            ]
        except (AttributeError, OSError, RuntimeError):
            return []

    def _targets_detect(self):
        detected = self._detections()
        return self._check("targets.detect", bool(detected), "Agent targets were detected", "Run skillcheck install --target all to configure supported Agents.")

    def _targets_mcp(self):
        detected = self._detections()
        return self._check("targets.mcp", bool(detected) and all(item.mcp_configured for item in detected), "Skillcheck MCP entries are configured", "Run skillcheck install to rewrite only Skillcheck MCP entries.")

    def _targets_instructions(self):
        detected = self._detections()
        return self._check("targets.instructions", bool(detected) and all(item.instructions_configured for item in detected), "Skillcheck instruction markers are configured", "Run skillcheck install to rewrite only Skillcheck marker blocks.")

    def _mcp_handshake(self):
        available = getattr(self.context, "mcp_available", None)
        if available is None:
            try:
                from skillcheck.mcp.server import TOOL_NAMES
                available = bool(TOOL_NAMES)
            except (ImportError, AttributeError):
                available = False
        return self._check("mcp.handshake", bool(available), "MCP server can be loaded", "Reinstall Skillcheck, then run skillcheck install again.")

    def _watcher_available(self):
        try:
            import watchfiles  # noqa: F401
            available = True
        except ImportError:
            available = False
        return self._check("watcher.available", available, "File watcher is available", "Install the official Skillcheck release with bundled watcher support.")

    def _reports_permissions(self):
        path = Path(getattr(self.context, "reports_path", "reports"))
        writable = (path.exists() and os.access(path, os.W_OK)) or (not path.exists() and os.access(path.parent, os.W_OK))
        return self._check("reports.permissions", writable, "Report directory is writable", f"Create or grant write access to {path}.")
