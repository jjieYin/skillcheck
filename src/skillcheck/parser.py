from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

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
    metadata = yaml.safe_load(raw_metadata) or {}
    if not isinstance(metadata, dict):
        raise SkillParseError("SKILL.md frontmatter must be a YAML mapping")
    return dict(metadata), "".join(lines[closing_index + 1 :])


def canonical_skill_bytes(root: Path) -> bytes:
    """Return deterministic bytes for all safe regular files beneath ``root``."""

    root = Path(root)
    if not root.is_dir():
        raise SkillParseError(f"Skill root is not a directory: {root}")
    root_resolved = root.resolve()
    digest = hashlib.sha256()
    files: list[Path] = []
    for path in root.rglob("*"):
        if ".git" in path.parts or path.is_symlink() or not path.is_file():
            continue
        try:
            resolved = path.resolve()
            resolved.relative_to(root_resolved)
        except (OSError, ValueError):
            continue
        files.append(path)

    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.digest()


def content_hash(root: Path) -> str:
    return f"sha256:{hashlib.sha256(canonical_skill_bytes(root)).hexdigest()}"


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
    digest = content_hash(root)
    skill_id = _text_value(metadata.get("id")) or _path_skill_id(name, root)
    return SkillRecord(
        skill_id=skill_id,
        name=name,
        description=description,
        root_path=root.resolve(),
        provider=provider,
        scope=scope,
        body=body.strip(),
        content_hash=digest,
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
