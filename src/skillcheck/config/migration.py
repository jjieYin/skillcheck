from __future__ import annotations

from copy import deepcopy
from typing import Any


def deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge(target[key], value)
        else:
            target[key] = value


def migrate_payload(raw: dict[str, Any], defaults: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Convert the v1 flat config to schema v2 without retaining secrets."""
    schema_version = raw.get("schema_version", 1)
    if isinstance(schema_version, int) and schema_version >= 2:
        payload = deepcopy(defaults)
        deep_merge(payload, raw)
        return payload, False

    payload = deepcopy(defaults)
    deep_merge(payload, raw)
    if "extra_paths" in raw:
        payload.setdefault("scan", {})["extra_paths"] = raw["extra_paths"]
    if "llm" in raw and isinstance(raw["llm"], dict):
        payload.setdefault("legacy", {})["llm"] = deepcopy(raw["llm"])
        migrated_llm = deepcopy(raw["llm"])
        migrated_llm["enabled"] = False
        payload["llm"] = migrated_llm
    payload["schema_version"] = 2
    return payload, True
