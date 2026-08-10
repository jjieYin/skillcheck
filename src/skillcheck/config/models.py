from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ReviewMode = Literal["ask", "none", "codex", "claude"]


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


class ScanConfig(BaseModel):
    extra_paths: list[Path] = Field(default_factory=list)
    follow_symlinks: bool = False


class ReviewConfig(BaseModel):
    mode: ReviewMode = "ask"
    preferred_agent: Literal["codex", "claude"] | None = None
    allow_full_text: bool = False
    max_groups_per_request: int = Field(default=10, ge=1, le=50)
    timeout_seconds: int = Field(default=120, ge=10, le=600)
    direct_api_compat: bool = False


class EmbeddingConfig(BaseModel):
    backend: str = "hash"
    model_id: str = "hash-v1"
    dimensions: int = 256
    local_model: str | None = None


class LLMConfig(BaseModel):
    enabled: bool = False
    provider: str = "openai"
    model: str = "qwen-plus"
    base_url: str | None = None
    api_key_env: str | None = None
    allow_full_text: bool = False

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) if self.api_key_env else None


class SecurityConfig(BaseModel):
    enabled: bool = True
    skill_spector_command: str | None = None
    timeout_seconds: int = 30


class ThresholdConfig(BaseModel):
    top_k: int = 5
    duplicate_similarity: float = 0.98
    overlap_similarity: float = 0.86
    variant_similarity: float = 0.82
    conflict_similarity: float = 0.80


class TargetConfig(BaseModel):
    configured: list[str] = Field(default_factory=list)
    scope: Literal["global", "project"] = "global"
    last_validated: bool = False


class ReportsConfig(BaseModel):
    open_after_scan: Literal["ask", "always", "never"] = "ask"
    formats: list[str] = Field(default_factory=lambda: ["markdown", "json"])


class PrivacyConfig(BaseModel):
    redact_secrets: bool = True
    include_body_excerpts: bool = True


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: int = 2
    scan_paths: list[Path] = Field(default_factory=list)
    index_path: Path
    reports_path: Path
    staging_path: Path
    scan: ScanConfig = Field(default_factory=ScanConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    targets: TargetConfig = Field(default_factory=TargetConfig)
    reports: ReportsConfig = Field(default_factory=ReportsConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    thresholds: ThresholdConfig = Field(default_factory=ThresholdConfig)
    legacy: dict[str, object] = Field(default_factory=dict)

    @property
    def extra_paths(self) -> list[Path]:
        return self.scan.extra_paths

    @extra_paths.setter
    def extra_paths(self, value: list[Path]) -> None:
        self.scan.extra_paths = value

    @classmethod
    def default(cls, home: Path | str | None = None) -> "AppConfig":
        user_home = Path(home).expanduser() if home is not None else Path.home()
        state = app_home(home)
        paths = unique_paths([
            user_home / ".codex" / "skills",
            user_home / ".agents" / "skills",
            user_home / ".claude" / "skills",
            user_home / ".cursor" / "rules",
            Path.cwd() / ".codex" / "skills",
            Path.cwd() / ".agents" / "skills",
            Path.cwd() / ".claude" / "skills",
        ])
        return cls(
            scan_paths=paths,
            index_path=state / "index.db",
            reports_path=state / "reports",
            staging_path=state / "staging",
        )

    def effective_review_mode(self, *, interactive: bool, cli_value: str | None) -> str:
        if cli_value is not None:
            return cli_value
        if not interactive:
            return "none"
        return self.review.mode
