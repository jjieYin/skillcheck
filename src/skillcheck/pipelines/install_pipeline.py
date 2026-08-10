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
    path: Path
    before_hash: str | None
    after_text: str
    kind: Literal["mcp", "instructions"]


class InstallPreview(BaseModel):
    agents: list[str]
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
        changes: list[FileChangePreview] = []
        for agent in normalized_agents:
            target = self.registry.get(agent)
            mcp = target.preview(scope)
            instructions = target.preview_instructions(scope, self.instruction_text)
            changes.extend(
                [
                    FileChangePreview(
                        path=mcp.path,
                        before_hash=mcp.before_hash,
                        after_text=mcp.after_text,
                        kind="mcp",
                    ),
                    FileChangePreview(
                        path=instructions.path,
                        before_hash=instructions.before_hash,
                        after_text=instructions.after_text,
                        kind="instructions",
                    ),
                ]
            )
        return InstallPreview(agents=normalized_agents, scope=scope, changes=changes)

    def apply(self, preview: InstallPreview, *, confirmed: bool) -> InstallResult:
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
        except Exception:
            self._rollback(applied)
            raise
        return InstallResult(changed_files=changed_files, validations=validations)

    @staticmethod
    def _normalize_agents(agents: list[str]) -> list[str]:
        if not agents:
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
