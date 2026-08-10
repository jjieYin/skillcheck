"""Read-only Claude Code CLI review adapter."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from skillcheck.reviewers.base import ReviewCapability, ReviewExecution
from skillcheck.reviewers.codex import _resolve_cli
from skillcheck.reviewers.process import run_agent


class ClaudeReviewAdapter:
    agent = "claude"

    def __init__(
        self,
        executable: Path | str | None = None,
        *,
        runner: Any = None,
        schema_path: Path | str | None = None,
        timeout_seconds: int = 120,
        search_path: Iterable[Path] | None = None,
    ) -> None:
        self.executable = Path(executable).expanduser() if executable else _resolve_cli("claude", search_path)
        self.runner = runner
        self.schema_path = Path(schema_path).expanduser() if schema_path else Path(__file__).with_name("schemas") / "agent-review.schema.json"
        self.timeout_seconds = timeout_seconds

    def detect(self) -> ReviewCapability:
        if self.executable is None:
            return ReviewCapability(agent=self.agent, available=False, reason="未找到 claude 可执行文件")
        return ReviewCapability(agent=self.agent, available=True, executable=self.executable)

    def review(self, packet) -> ReviewExecution:
        if self.executable is None:
            return ReviewExecution(returncode=-1, stdout="", stderr="claude executable unavailable")
        if not self.schema_path.is_file():
            return ReviewExecution(returncode=-1, stdout="", stderr="review schema unavailable")
        command = [
            str(self.executable),
            "--print",
            "--output-format",
            "json",
            "--json-schema",
            self.schema_path.read_text(encoding="utf-8"),
            "--permission-mode",
            "plan",
            "--no-session-persistence",
        ]
        prompt = packet.model_dump_json()
        return run_agent(
            command,
            prompt,
            timeout_seconds=self.timeout_seconds,
            runner=self.runner or __import__("subprocess"),
        )


ClaudeAdapter = ClaudeReviewAdapter

