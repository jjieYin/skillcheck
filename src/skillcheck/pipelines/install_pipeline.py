"""Preview-first installation of the local Skillcheck MCP integration."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from skillcheck.mcp.instructions import MCP_INSTRUCTIONS
from skillcheck.targets.base import DetectionResult
from skillcheck.targets.config_io import atomic_replace, content_hash
from skillcheck.targets.registry import TargetRegistry


class InstallDiscovery(BaseModel):
    agents: list[DetectionResult]


class FileChangePreview(BaseModel):
    agent: str
    path: Path
    before_hash: str | None
    after_text: str
    kind: Literal["mcp", "instructions"]
    operation: Literal["install", "remove"] = "install"


class InstallPreview(BaseModel):
    agents: list[str]
    scope: Literal["global", "project"]
    changes: list[FileChangePreview]


class InstallReconcilePreview(BaseModel):
    """Preview an exact Agent selection reconciliation."""

    previous_agents: list[str]
    selected_agents: list[str]
    added: list[str]
    kept: list[str]
    removed: list[str]
    scope: Literal["global", "project"]
    changes: list[FileChangePreview]


class InstallResult(BaseModel):
    changed_files: list[Path]
    validations: list[str]


class InstallPipeline:
    """Atomically apply an MCP entry and owned instruction block per Agent."""

    def __init__(
        self,
        registry: TargetRegistry,
        *,
        instruction_text: str = MCP_INSTRUCTIONS,
        smoke_check: Callable[[], str] | None = None,
    ) -> None:
        self.registry = registry
        self.instruction_text = instruction_text
        self.smoke_check = smoke_check or self._smoke_check

    def discover(self) -> InstallDiscovery:
        return InstallDiscovery(agents=self.registry.detect_all())

    def preview(self, agents: list[str], *, scope: Literal["global", "project"]) -> InstallPreview:
        normalized_agents = self._normalize_agents(agents)
        changes = self._preview_changes(normalized_agents, scope=scope, operation="install")
        return InstallPreview(agents=normalized_agents, scope=scope, changes=changes)

    def preview_reconcile(
        self,
        previous_agents: list[str],
        selected_agents: list[str],
        *,
        scope: Literal["global", "project"],
    ) -> InstallReconcilePreview:
        previous = self._normalize_agents(previous_agents, allow_empty=True)
        selected = self._normalize_agents(selected_agents, allow_empty=True)
        previous_set = set(previous)
        selected_set = set(selected)
        added = [agent for agent in selected if agent not in previous_set]
        kept = [agent for agent in selected if agent in previous_set]
        removed = [agent for agent in previous if agent not in selected_set]
        changes = self._preview_changes(selected, scope=scope, operation="install")
        changes.extend(self._preview_changes(removed, scope=scope, operation="remove"))
        return InstallReconcilePreview(
            previous_agents=previous,
            selected_agents=selected,
            added=added,
            kept=kept,
            removed=removed,
            scope=scope,
            changes=changes,
        )

    def apply(
        self,
        preview: InstallPreview,
        *,
        confirmed: bool,
        on_success: Callable[[], None] | None = None,
    ) -> InstallResult:
        if not confirmed:
            return InstallResult(changed_files=[], validations=[])
        applied: list[tuple[FileChangePreview, bool, str]] = []
        changed_files: list[Path] = []
        try:
            for change in preview.changes:
                existed = change.path.exists()
                before_text = change.path.read_text(encoding="utf-8") if existed else ""
                if before_text == change.after_text:
                    continue
                atomic_replace(change.path, change.after_text, expected_hash=change.before_hash)
                applied.append((change, existed, before_text))
                changed_files.append(change.path)
            validations: list[str] = []
            for agent in preview.agents:
                target = self.registry.get(agent)
                if not target.validate(preview.scope):
                    raise RuntimeError(f"MCP validation failed for {agent}")
                if not target.validate_instructions(preview.scope):
                    raise RuntimeError(f"instruction marker validation failed for {agent}")
                validations.append(f"{agent}: MCP entry and instruction markers validated")
            validations.append(self.smoke_check())
            if on_success is not None:
                on_success()
        except Exception:
            self._rollback(applied)
            raise
        return InstallResult(changed_files=changed_files, validations=validations)

    def apply_reconcile(
        self,
        preview: InstallReconcilePreview,
        *,
        confirmed: bool,
        on_success: Callable[[], None] | None = None,
    ) -> InstallResult:
        """Apply an exact selection, removing only Skillcheck-owned entries."""

        if not confirmed:
            return InstallResult(changed_files=[], validations=[])
        applied: list[tuple[FileChangePreview, bool, str]] = []
        changed_files: list[Path] = []
        try:
            for change in preview.changes:
                existed = change.path.exists()
                before_text = change.path.read_text(encoding="utf-8") if existed else ""
                if before_text == change.after_text:
                    continue
                atomic_replace(change.path, change.after_text, expected_hash=change.before_hash)
                applied.append((change, existed, before_text))
                changed_files.append(change.path)

            validations: list[str] = []
            for agent in preview.selected_agents:
                target = self.registry.get(agent)
                if not target.validate(preview.scope):
                    raise RuntimeError(f"MCP validation failed for {agent}")
                if not target.validate_instructions(preview.scope):
                    raise RuntimeError(f"instruction marker validation failed for {agent}")
                validations.append(f"{agent}: MCP entry and instruction markers validated")
            for agent in preview.removed:
                target = self.registry.get(agent)
                if not target.validate_absent(preview.scope):
                    raise RuntimeError(f"MCP removal validation failed for {agent}")
                if not target.validate_instructions_absent(preview.scope):
                    raise RuntimeError(f"instruction marker removal validation failed for {agent}")
                validations.append(f"{agent}: MCP entry and instruction markers removed")
            if preview.selected_agents:
                validations.append(self.smoke_check())
            if on_success is not None:
                on_success()
        except Exception:
            self._rollback(applied)
            raise
        return InstallResult(changed_files=changed_files, validations=validations)

    def _preview_changes(
        self,
        agents: list[str],
        *,
        scope: Literal["global", "project"],
        operation: Literal["install", "remove"],
    ) -> list[FileChangePreview]:
        changes: list[FileChangePreview] = []
        for agent in agents:
            target = self.registry.get(agent)
            if operation == "install":
                mcp = target.preview(scope)
                instructions = target.preview_instructions(scope, self.instruction_text)
            else:
                mcp = target.preview_uninstall(scope)
                instructions = target.preview_uninstall_instructions(scope)
            changes.extend(
                [
                    FileChangePreview(
                        agent=agent,
                        path=mcp.path,
                        before_hash=mcp.before_hash,
                        after_text=mcp.after_text,
                        kind="mcp",
                        operation=operation,
                    ),
                    FileChangePreview(
                        agent=agent,
                        path=instructions.path,
                        before_hash=instructions.before_hash,
                        after_text=instructions.after_text,
                        kind="instructions",
                        operation=operation,
                    ),
                ]
            )
        return changes

    @staticmethod
    def _normalize_agents(agents: list[str], *, allow_empty: bool = False) -> list[str]:
        if not agents and not allow_empty:
            raise ValueError("at least one Agent target is required")
        result: list[str] = []
        for agent in agents:
            normalized = str(agent).casefold()
            if normalized not in result:
                result.append(normalized)
        return result

    @staticmethod
    def _rollback(applied: list[tuple[FileChangePreview, bool, str]]) -> None:
        for change, existed, before_text in reversed(applied):
            try:
                if existed:
                    atomic_replace(
                        change.path,
                        before_text,
                        expected_hash=content_hash(change.path),
                    )
                elif change.path.exists():
                    change.path.unlink()
            except OSError:
                # Preserve the original write error; callers can inspect the path manually.
                pass

    @staticmethod
    def _smoke_check() -> str:
        """Confirm the stdio MCP process can start without issuing it a request."""

        command = [sys.executable, "-m", "skillcheck.app.main", "serve", "--mcp"]
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            try:
                process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                return "skillcheck serve --mcp smoke startup passed"
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise RuntimeError(f"skillcheck serve --mcp exited during smoke startup: {stderr.strip()}")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
