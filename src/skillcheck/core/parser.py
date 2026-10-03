from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from skillcheck.core.fingerprints import FingerprintBuilder
from skillcheck.models import Provider, Scope, SkillRecord


class SkillParseError(ValueError):
    """Raised when a local Skill package cannot be parsed safely."""


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse optional YAML frontmatter and return metadata plus Markdown body."""

    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text

    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing_index is None:
        raise SkillParseError("SKILL.md frontmatter is missing its closing --- marker")

    raw_metadata = "".join(lines[1:closing_index])
    try:
        metadata = yaml.safe_load(raw_metadata) or {}
    except yaml.YAMLError as exc:
        raise SkillParseError("SKILL.md frontmatter is not valid YAML") from exc
    if not isinstance(metadata, dict):
        raise SkillParseError("SKILL.md frontmatter must be a YAML mapping")
    return dict(metadata), "".join(lines[closing_index + 1 :])


def canonical_skill_bytes(root: Path) -> bytes:
    """Return deterministic bytes for all safe regular files beneath ``root``."""

    from skillcheck.core.fingerprints import _canonical_files_bytes

    try:
        return _canonical_files_bytes(Path(root))
    except (OSError, ValueError) as exc:
        raise SkillParseError(f"cannot fingerprint Skill root: {root}") from exc


def content_hash(root: Path) -> str:
    return f"sha256:{hashlib.sha256(canonical_skill_bytes(root)).hexdigest()}"


def instruction_hash(root: Path) -> str:
    """Hash the parsed SKILL.md instructions, independent of package assets.

    Frontmatter is serialized as semantic JSON with sorted keys, while the
    Markdown body uses LF line endings, no trailing line whitespace, and one
    final newline.  This keeps the identity stable across formatting-only
    rewrites without hiding meaningful instruction changes.
    """

    root = Path(root).expanduser()
    skill_file = root / "SKILL.md"
    if not skill_file.is_file():
        raise SkillParseError(f"SKILL.md not found in Skill root: {root}")
    try:
        text = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SkillParseError(f"cannot read SKILL.md: {root}") from exc
    metadata, body = parse_frontmatter(text)
    normalized_metadata = json.dumps(
        _canonical_metadata(metadata), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    normalized_body = _normalize_instruction_body(body)
    payload = f"{normalized_metadata}\n---\n{normalized_body}".encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def parse_skill(
    root: Path,
    provider: Provider | None = None,
    scope: Scope | None = None,
) -> SkillRecord:
    root = Path(root).expanduser()
    skill_file = root / "SKILL.md"
    if not skill_file.is_file():
        raise SkillParseError(f"SKILL.md not found in Skill root: {root}")

    try:
        text = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SkillParseError(f"cannot read SKILL.md: {root}") from exc

    metadata, body = parse_frontmatter(text)
    name = _text_value(metadata.get("name")) or root.name
    description = _text_value(metadata.get("description"))
    fingerprints = FingerprintBuilder().build(root, metadata=metadata, body=body)
    skill_id = _text_value(metadata.get("id")) or _path_skill_id(name, root)
    return SkillRecord(
        skill_id=skill_id,
        name=name,
        description=description,
        root_path=root.resolve(),
        provider=provider,
        scope=scope,
        body=body.strip(),
        content_hash=fingerprints.package_hash,
        instruction_hash=instruction_hash(root),
        behavior_hash=fingerprints.behavior_hash,
        execution_hash=fingerprints.execution_hash,
        hash_algorithm_revision=fingerprints.hash_algorithm_revision,
        license=_text_value(metadata.get("license")),
        compatibility=_text_value(metadata.get("compatibility")),
        metadata=_mapping_value(metadata.get("metadata")),
        allowed_tools=_list_value(metadata.get("allowed-tools")),
        tools=_list_value(metadata.get("tools")),
        permissions=_list_value(metadata.get("permissions")),
        environments=_list_value(metadata.get("environments")),
        inputs=_list_value(metadata.get("inputs")),
        outputs=_list_value(metadata.get("outputs")),
    )


def _path_skill_id(name: str, root: Path) -> str:
    path_digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:12]
    return f"{name}:{path_digest}"


def _text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _mapping_value(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _canonical_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical_metadata(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_metadata(item) for item in value]
    if isinstance(value, set):
        return sorted(_canonical_metadata(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _normalize_instruction_body(body: str) -> str:
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    return normalized.rstrip("\n") + "\n"
