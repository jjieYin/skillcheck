from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from skillcheck.config.models import AppConfig, app_home


def yaml_payload(config: AppConfig) -> dict[str, Any]:
    return config.model_dump(mode="json")


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def save_config(path: Path | str, config: AppConfig) -> None:
    """Persist a validated v4 configuration through an atomic swap."""

    config_path = Path(path).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(
        config_path,
        yaml.safe_dump(yaml_payload(config), sort_keys=False, allow_unicode=True),
    )


def load_config(
    path: Path | str | None = None,
    *,
    home: Path | str | None = None,
    create: bool = True,
) -> AppConfig:
    config_path = Path(path).expanduser() if path is not None else app_home(home) / "config.yaml"
    if not config_path.exists():
        config = AppConfig.default(home=home)
        if create:
            save_config(config_path, config)
        return config

    raw: Any = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise TypeError(f"configuration root must be a mapping: {config_path}")
    if raw.get("schema_version") != 4:
        found = raw.get("schema_version", "missing")
        raise ValueError(
            f"Unsupported configuration schema_version {found!r}; expected schema_version 4. "
            "Remove the old Skillcheck configuration and run skillcheck install again."
        )
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as error:
        extra_fields = [
            ".".join(str(item) for item in detail["loc"])
            for detail in error.errors()
            if detail["type"] == "extra_forbidden"
        ]
        if extra_fields:
            raise ValueError(
                "configuration contains unsupported fields: " + ", ".join(extra_fields)
            ) from error
        raise ValueError(f"invalid v4 configuration: {error}") from error
