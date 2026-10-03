"""Deterministic package, behavior and execution fingerprints for Skills."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

HASH_ALGORITHM_REVISION = "2"
EMPTY_EXECUTION_HASH = "sha256-v2:empty-scripts"


class FingerprintError(ValueError):
    """Raised when a Skill root cannot be fingerprinted safely."""


class FingerprintResult:
    """The three independent identities of one Skill package."""

    __slots__ = ("behavior_hash", "execution_hash", "hash_algorithm_revision", "package_hash")

    def __init__(
        self,
        package_hash: str,
        behavior_hash: str,
        execution_hash: str | None,
        hash_algorithm_revision: str = HASH_ALGORITHM_REVISION,
    ) -> None:
        self.package_hash = package_hash
        self.behavior_hash = behavior_hash
        self.execution_hash = execution_hash
        self.hash_algorithm_revision = hash_algorithm_revision


class FingerprintBuilder:
    """Build versioned fingerprints without interpreting Skill prose semantically."""

    def build(
        self, root: Path, *, metadata: Mapping[str, Any], body: str
    ) -> FingerprintResult:
        root = Path(root).expanduser()
        if not root.is_dir():
            raise FingerprintError(f"Skill root is not a directory: {root}")
        return FingerprintResult(
            package_hash=_package_hash(root),
            behavior_hash=_behavior_hash(metadata, body),
            execution_hash=_execution_hash(root),
        )


def _package_hash(root: Path) -> str:
    return f"sha256:{hashlib.sha256(_canonical_files_bytes(root)).hexdigest()}"


def _behavior_hash(metadata: Mapping[str, Any], body: str) -> str:
    selected = {
        "description": _text(metadata.get("description")),
        "compatibility": _text(metadata.get("compatibility")),
        "allowed-tools": _collection(metadata.get("allowed-tools")),
        "tools": _collection(metadata.get("tools")),
        "permissions": _collection(metadata.get("permissions")),
        "environments": _collection(metadata.get("environments")),
        "inputs": _collection(metadata.get("inputs")),
        "outputs": _collection(metadata.get("outputs")),
        "body": _normalize_body(body),
    }
    payload = json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256-v{HASH_ALGORITHM_REVISION}:{digest}"


def _execution_hash(root: Path) -> str | None:
    files: list[Path] = []
    root_resolved = root.resolve()
    for candidate in root.rglob("*"):
        if candidate.is_symlink() or not candidate.is_file() or ".git" in candidate.parts:
            continue
        relative = candidate.relative_to(root).as_posix()
        if not relative.casefold().startswith("scripts/"):
            continue
        try:
            candidate.resolve().relative_to(root_resolved)
        except (OSError, ValueError):
            continue
        files.append(candidate)
    if not files:
        return EMPTY_EXECUTION_HASH
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        try:
            relative = path.relative_to(root).as_posix()
            content = path.read_bytes()
        except (OSError, UnicodeError):
            return None
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return f"sha256-v{HASH_ALGORITHM_REVISION}:{digest.hexdigest()}"


def _canonical_files_bytes(root: Path) -> bytes:
    root_resolved = root.resolve()
    digest = hashlib.sha256()
    files: list[Path] = []
    for path in root.rglob("*"):
        if ".git" in path.parts or path.is_symlink() or not path.is_file():
            continue
        try:
            path.resolve().relative_to(root_resolved)
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


def _collection(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]
    return sorted({str(item).strip() for item in values if str(item).strip()}, key=str.casefold)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _normalize_body(body: str) -> str:
    normalized = str(body).replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    return normalized.rstrip("\n") + "\n"
