from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class RootScope(StrEnum):
    GLOBAL = "global"
    PROJECT = "project"
    CUSTOM = "custom"


class SkillStatus(StrEnum):
    ACTIVE = "active"
    INVALID = "invalid"
    MISSING = "missing"


class LibraryRoot(BaseModel):
    model_config = ConfigDict(frozen=True)

    root_id: str
    path: Path
    provider: str
    scope: RootScope
    project_path: Path | None = None
    enabled: bool = True


class SkillSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    skill_id: str
    root_id: str
    relative_path: str
    name: str
    description: str = ""
    body: str = ""
    content_hash: str
    status: SkillStatus = SkillStatus.ACTIVE
    tools: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    environments: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    indexed_at: datetime
    parse_error: str | None = None


class SyncSummary(BaseModel):
    revision: str
    added: int = 0
    updated: int = 0
    removed: int = 0
    invalid: int = 0
    pending: int = 0
    warnings: list[str] = Field(default_factory=list)


class SyncEvent(BaseModel):
    event_id: str
    revision: str
    started_at: datetime
    completed_at: datetime
    added: int = 0
    updated: int = 0
    removed: int = 0
    invalid: int = 0
    warnings: list[str] = Field(default_factory=list)
