"""Common Agent review adapter types."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class ReviewCapability(BaseModel):
    agent: str
    available: bool
    executable: Path | None = None
    reason: str | None = None


class ReviewExecution(BaseModel):
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


class ReviewAdapter(Protocol):
    def detect(self) -> ReviewCapability: ...

    def review(self, packet) -> ReviewExecution: ...

