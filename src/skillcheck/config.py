from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


def app_home(home: Path | str | None = None) -> Path:
    """Return the directory used for skillcheck's local state.

    ``SKILLCHECK_HOME`` is intentionally checked before the optional argument so
    command-line smoke tests and isolated users can redirect all state without
    editing the YAML file.
    """

    configured = os.environ.get("SKILLCHECK_HOME")
    if configured:
        return Path(configured).expanduser()
    if home is None:
        return Path.home() / ".skillcheck"
    return Path(home).expanduser() / ".skillcheck"


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


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scan_paths: list[Path] = Field(default_factory=list)
    extra_paths: list[Path] = Field(default_factory=list)
    index_path: Path
    reports_path: Path
    staging_path: Path
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    thresholds: ThresholdConfig = Field(default_factory=ThresholdConfig)

    @classmethod
    def default(cls, home: Path | str | None = None) -> AppConfig:
        user_home = Path(home).expanduser() if home is not None else Path.home()
        state = app_home(home)
        paths = [
            user_home / ".codex" / "skills",
            user_home / ".agents" / "skills",
            user_home / ".claude" / "skills",
            user_home / ".cursor" / "rules",
            Path.cwd() / ".codex" / "skills",
            Path.cwd() / ".agents" / "skills",
            Path.cwd() / ".claude" / "skills",
        ]
        return cls(
            scan_paths=_unique_paths(paths),
            index_path=state / "index.db",
            reports_path=state / "reports",
            staging_path=state / "staging",
        )


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        resolved = path.expanduser()
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            result.append(resolved)
    return result


def load_or_create_config(
    path: Path | str | None = None,
    *,
    home: Path | str | None = None,
) -> AppConfig:
    """Load YAML configuration, creating a secret-free default if missing."""

    config_path = Path(path).expanduser() if path is not None else app_home(home) / "config.yaml"
    if not config_path.exists():
        config = AppConfig.default(home=home)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            yaml.safe_dump(_yaml_payload(config), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return config

    raw: Any = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise TypeError(f"configuration root must be a mapping: {config_path}")

    defaults = AppConfig.default(home=home)
    payload = _yaml_payload(defaults)
    _deep_merge(payload, raw)
    return AppConfig.model_validate(payload)


def _yaml_payload(config: AppConfig) -> dict[str, Any]:
    return {
        "scan_paths": [str(path) for path in config.scan_paths],
        "extra_paths": [str(path) for path in config.extra_paths],
        "index_path": str(config.index_path),
        "reports_path": str(config.reports_path),
        "staging_path": str(config.staging_path),
        "embedding": config.embedding.model_dump(mode="json"),
        "llm": config.llm.model_dump(mode="json"),
        "security": config.security.model_dump(mode="json"),
        "thresholds": config.thresholds.model_dump(mode="json"),
    }


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
