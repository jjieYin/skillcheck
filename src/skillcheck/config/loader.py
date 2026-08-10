from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from skillcheck.config.migration import migrate_payload
from skillcheck.config.models import AppConfig, app_home


def yaml_payload(config: AppConfig) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "scan_paths": [str(path) for path in config.scan_paths],
        "index_path": str(config.index_path),
        "reports_path": str(config.reports_path),
        "staging_path": str(config.staging_path),
        "scan": {
            "extra_paths": [str(path) for path in config.scan.extra_paths],
            "follow_symlinks": config.scan.follow_symlinks,
        },
        "review": config.review.model_dump(mode="json"),
        "targets": config.targets.model_dump(mode="json"),
        "reports": config.reports.model_dump(mode="json"),
        "privacy": config.privacy.model_dump(mode="json"),
        "embedding": config.embedding.model_dump(mode="json"),
        "llm": config.llm.model_dump(mode="json"),
        "security": config.security.model_dump(mode="json"),
        "thresholds": config.thresholds.model_dump(mode="json"),
        "legacy": config.legacy,
    }


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def load_or_create_config(
    path: Path | str | None = None,
    *,
    home: Path | str | None = None,
) -> AppConfig:
    config_path = Path(path).expanduser() if path is not None else app_home(home) / "config.yaml"
    if not config_path.exists():
        config = AppConfig.default(home=home)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(
            config_path,
            yaml.safe_dump(yaml_payload(config), sort_keys=False, allow_unicode=True),
        )
        return config

    raw: Any = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise TypeError(f"configuration root must be a mapping: {config_path}")

    defaults = yaml_payload(AppConfig.default(home=home))
    payload, migrated = migrate_payload(raw, defaults)
    if migrated:
        backup = config_path.with_suffix(config_path.suffix + ".v1.bak")
        if not backup.exists():
            shutil.copy2(config_path, backup)
        _atomic_write(
            config_path,
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        )
    return AppConfig.model_validate(payload)
