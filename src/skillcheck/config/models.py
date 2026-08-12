from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def app_home(home: Path | str | None = None) -> Path:
    configured = os.environ.get("SKILLCHECK_HOME")
    if configured:
        return Path(configured).expanduser()
    if home is None:
        return Path.home() / ".skillcheck"
    return Path(home).expanduser() / ".skillcheck"


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        expanded = Path(path).expanduser()
        key = os.path.normcase(str(expanded))
        if key not in seen:
            seen.add(key)
            result.append(expanded)
    return result


class StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmbeddingConfig(StrictConfig):
    backend: str = "hash"
    model_id: str = "hash-v1"
    dimensions: int = 256
    local_model: str | None = None


class SecurityConfig(StrictConfig):
    enabled: bool = True
    skill_spector_command: str | None = None
    timeout_seconds: int = 30


class ThresholdConfig(StrictConfig):
    top_k: int = 5
    duplicate_similarity: float = 0.98
    overlap_similarity: float = 0.86
    variant_similarity: float = 0.82
    conflict_similarity: float = 0.80


class TargetConfig(StrictConfig):
    configured: list[str] = Field(default_factory=list)
    # Once initialized, the picker reuses this exact list on subsequent runs.
    selection_initialized: bool = False
    scope: Literal["global", "project"] = "global"
    last_validated: bool = False


class ReportsConfig(StrictConfig):
    directory: Path = Field(default_factory=lambda: app_home() / "reports")
    formats: list[str] = Field(default_factory=lambda: ["markdown", "json"])


class PrivacyConfig(StrictConfig):
    redact_secrets: bool = True
    include_body_excerpts: bool = True


class CatalogConfig(StrictConfig):
    initialized: bool = False
    roots: list[Path] = Field(default_factory=list)
    database_path: Path = Field(default_factory=lambda: app_home() / "index.db")
    staging_path: Path = Field(default_factory=lambda: app_home() / "staging")
    debounce_ms: int = Field(default=2000, ge=100, le=60000)
    reconcile_before_query: bool = True


class AppConfig(StrictConfig):
    """Strict, migration-free configuration for the v0.4 catalog."""

    schema_version: Literal[4] = 4
    catalog: CatalogConfig
    targets: TargetConfig = Field(default_factory=TargetConfig)
    reports: ReportsConfig = Field(default_factory=ReportsConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    thresholds: ThresholdConfig = Field(default_factory=ThresholdConfig)

    @classmethod
    def default(cls, home: Path | str | None = None) -> AppConfig:
        user_home = Path(home).expanduser() if home is not None else Path.home()
        state = app_home(home)
        roots = unique_paths(
            [
                user_home / ".codex" / "skills",
                user_home / ".agents" / "skills",
                user_home / ".claude" / "skills",
                user_home / ".cursor" / "rules",
                Path.cwd() / ".codex" / "skills",
                Path.cwd() / ".agents" / "skills",
                Path.cwd() / ".claude" / "skills",
            ]
        )
        return cls(
            catalog=CatalogConfig(
                roots=roots,
                database_path=state / "index.db",
                staging_path=state / "staging",
            ),
            reports=ReportsConfig(directory=state / "reports"),
        )
