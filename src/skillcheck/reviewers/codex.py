"""Read-only Codex CLI review adapter."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from skillcheck.reviewers.base import ReviewCapability, ReviewExecution
from skillcheck.reviewers.process import run_agent


def _resolve_cli(name: str, search_path: Iterable[Path] | None = None) -> Path | None:
    directories = [Path(item) for item in search_path] if search_path is not None else None
    suffixes = (".exe", ".cmd", "") if os.name == "nt" else ("",)
    if directories is not None:
        for directory in directories:
            for suffix in suffixes:
                candidate = directory / f"{name}{suffix}"
                if candidate.is_file():
                    return candidate.resolve()
        return None
    import shutil

    for suffix in suffixes:
        value = shutil.which(f"{name}{suffix}")
        if value:
            return Path(value).resolve()
    return None


class CodexReviewAdapter:
    agent = "codex"

    def __init__(
        self,
        executable: Path | str | None = None,
        *,
        runner: Any = None,
        schema_path: Path | str | None = None,
        timeout_seconds: int = 120,
        search_path: Iterable[Path] | None = None,
    ) -> None:
        self.executable = Path(executable).expanduser() if executable else _resolve_cli("codex", search_path)
        self.runner = runner
        self.schema_path = Path(schema_path).expanduser() if schema_path else self._default_schema()
        self.timeout_seconds = timeout_seconds
        self.last_output_hash: str | None = None

    @staticmethod
    def _default_schema() -> Path:
        return Path(__file__).with_name("schemas") / "agent-review.schema.json"

    def detect(self) -> ReviewCapability:
        if self.executable is None:
            return ReviewCapability(agent=self.agent, available=False, reason="未找到 codex 可执行文件")
        return ReviewCapability(agent=self.agent, available=True, executable=self.executable)

    def review(self, packet) -> ReviewExecution:
        if self.executable is None:
            return ReviewExecution(returncode=-1, stdout="", stderr="codex executable unavailable")
        if not self.schema_path.is_file():
            return ReviewExecution(returncode=-1, stdout="", stderr="review schema unavailable")
        with tempfile.NamedTemporaryFile(prefix="skillcheck-codex-", suffix=".json", delete=False) as handle:
            output_path = Path(handle.name)
        try:
            command = [
                str(self.executable),
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--output-schema",
                str(self.schema_path),
                "--output-last-message",
                str(output_path),
                "-",
            ]
            prompt = packet.model_dump_json()
            execution = run_agent(
                command,
                prompt,
                timeout_seconds=self.timeout_seconds,
                runner=self.runner or __import__("subprocess"),
            )
            self.last_output_hash = __import__("hashlib").sha256(
                execution.stdout.encode("utf-8", errors="replace")
            ).hexdigest()
            return execution
        finally:
            try:
                output_path.unlink()
            except OSError:
                pass


CodexAdapter = CodexReviewAdapter

