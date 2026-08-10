"""Restricted subprocess execution for local Agent CLIs."""

from __future__ import annotations

import hashlib
import subprocess
from typing import Any

from skillcheck.reviewers.base import ReviewExecution


MAX_OUTPUT_CHARS = 200_000


def run_agent(
    command: list[str],
    prompt: str,
    *,
    timeout_seconds: int,
    runner: Any = subprocess,
) -> ReviewExecution:
    try:
        completed = runner.run(
            command,
            input=prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
        stdout = str(getattr(completed, "stdout", "") or "")
        stderr = str(getattr(completed, "stderr", "") or "")
        return ReviewExecution(
            returncode=int(getattr(completed, "returncode", 0)),
            stdout=stdout[:MAX_OUTPUT_CHARS],
            stderr=stderr[:MAX_OUTPUT_CHARS],
        )
    except subprocess.TimeoutExpired as exc:
        stdout = str(getattr(exc, "stdout", "") or "")
        stderr = str(getattr(exc, "stderr", "") or "")
        return ReviewExecution(
            returncode=-1,
            stdout=stdout[:MAX_OUTPUT_CHARS],
            stderr=stderr[:MAX_OUTPUT_CHARS] or "Agent review timed out",
            timed_out=True,
        )
    except OSError as exc:
        return ReviewExecution(returncode=-1, stdout="", stderr=type(exc).__name__)


def output_hash(execution: ReviewExecution) -> str:
    return hashlib.sha256(execution.stdout.encode("utf-8", errors="replace")).hexdigest()

