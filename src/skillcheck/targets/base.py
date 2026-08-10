"""Stable contracts shared by the Agent target adapters."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class AgentId(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"
    CURSOR = "cursor"
    AGENTS = "agents"


class DetectionResult(BaseModel):
    """Read-only preview of a locally detected Agent installation."""

    model_config = ConfigDict(frozen=True)

    agent: AgentId
    cli_path: Path | None = None
    config_path: Path | None = None
    skill_paths: list[Path] = Field(default_factory=list)
    mcp_configured: bool = False
    supports_global: bool = True
    supports_project: bool = True
    supports_review: bool = False


class ConfigChange(BaseModel):
    """A compare-and-swap configuration change awaiting confirmation."""

    model_config = ConfigDict(frozen=True)

    agent: AgentId
    path: Path
    before_hash: str | None = None
    after_text: str
    summary: list[str] = Field(default_factory=list)
    changed: bool = True


class AgentTarget(Protocol):
    """Adapter protocol implemented by each supported Agent."""

    agent: AgentId

    def detect(self) -> DetectionResult: ...

    def preview(self, scope: str) -> ConfigChange: ...

    def install(self, change: ConfigChange): ...

    def uninstall(self, scope: str): ...

    def validate(self, scope: str): ...

