from __future__ import annotations

import posixpath
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit
from zipfile import ZipFile


class SourceSafetyError(ValueError):
    """Raised when a Skill source is invalid or unsafe to stage."""


@dataclass(frozen=True)
class SourceLimits:
    max_files: int = 2_000
    max_unpacked_bytes: int = 100_000_000
    max_file_bytes: int = 20_000_000


class StagedSource:
    def __init__(self, source: str, root: Path, temporary_root: Path | None = None) -> None:
        self.source = source
        self.root = root
        self._temporary_root = temporary_root

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._temporary_root is not None and self._temporary_root.exists():
            shutil.rmtree(self._temporary_root, ignore_errors=True)
            self._temporary_root = None


def stage_source(
    source: str | Path,
    *,
    limits: SourceLimits | None = None,
    staging_parent: Path | str | None = None,
) -> StagedSource:
    """Validate and stage a directory, ZIP, or HTTPS GitHub repository."""

    limits = limits or SourceLimits()
    locator = str(source)
    if _is_github_url(locator):
        return _stage_github(locator, staging_parent=staging_parent)

    path = Path(source).expanduser()
    if not path.exists():
        raise SourceSafetyError(f"source does not exist: {source}")
    if path.is_symlink():
        raise SourceSafetyError("local source symlink is not allowed")
    if path.is_dir():
        _reject_source_symlinks(path)
        return StagedSource(locator, path.resolve())
    if path.is_file() and path.suffix.casefold() == ".zip":
        return _stage_zip(locator, path.resolve(), limits, staging_parent)
    raise SourceSafetyError("source must be a directory, ZIP archive, or HTTPS GitHub URL")


def _reject_source_symlinks(root: Path) -> None:
    for item in root.rglob("*"):
        if item.is_symlink():
            raise SourceSafetyError(f"source symlink is not allowed: {item}")


def _stage_zip(
    source: str,
    archive: Path,
    limits: SourceLimits,
    staging_parent: Path | str | None,
) -> StagedSource:
    temp_root = Path(tempfile.mkdtemp(prefix="skillcheck-stage-", dir=staging_parent))
    try:
        with ZipFile(archive) as zip_file:
            members = zip_file.infolist()
            if len(members) > limits.max_files:
                raise SourceSafetyError("ZIP file count exceeds safety limit")
            total_size = 0
            for member in members:
                relative = _safe_member_path(member.filename)
                if relative is None:
                    raise SourceSafetyError(f"ZIP path traversal is not allowed: {member.filename}")
                if _is_zip_symlink(member):
                    raise SourceSafetyError(f"ZIP symlink is not allowed: {member.filename}")
                if member.is_dir():
                    continue
                if member.file_size > limits.max_file_bytes:
                    raise SourceSafetyError(f"ZIP file exceeds per-file limit: {member.filename}")
                total_size += member.file_size
                if total_size > limits.max_unpacked_bytes:
                    raise SourceSafetyError("ZIP unpacked size exceeds safety limit")
                target = _safe_target(temp_root, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with zip_file.open(member, "r") as input_file, target.open("wb") as output_file:
                    while chunk := input_file.read(1024 * 1024):
                        written += len(chunk)
                        if written > limits.max_file_bytes or total_size - member.file_size + written > limits.max_unpacked_bytes:
                            raise SourceSafetyError("ZIP unpacked size exceeds safety limit")
                        output_file.write(chunk)
        return StagedSource(source, _locate_skill_root(temp_root), temp_root)
    except Exception:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise


def _stage_github(source: str, staging_parent: Path | str | None) -> StagedSource:
    _validate_github_url(source)
    if staging_parent is not None:
        Path(staging_parent).expanduser().mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix="skillcheck-stage-", dir=staging_parent))
    target = temp_root / "repo"
    try:
        subprocess.run(
            [
                "git",
                "-c",
                "http.followRedirects=false",
                "clone",
                "--depth",
                "1",
                "--filter=blob:limit=20m",
                source,
                str(target),
            ],
            check=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
        _reject_source_symlinks(target)
        return StagedSource(source, _locate_skill_root(target), temp_root)
    except SourceSafetyError:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise SourceSafetyError(f"GitHub source could not be cloned: {source}") from exc


def _is_github_url(source: str) -> bool:
    return source.startswith(("https://", "http://"))


def _validate_github_url(source: str) -> None:
    parsed = urlsplit(source)
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
        raise SourceSafetyError("source must be an HTTPS GitHub URL")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or any(part in {".", ".."} for part in parts):
        raise SourceSafetyError("source must be an HTTPS GitHub repository URL")


def _safe_member_path(name: str) -> str | None:
    normalized = posixpath.normpath(name.replace("\\", "/"))
    if not normalized or normalized in {".", "/"}:
        return None
    if normalized.startswith(("/", "../")) or normalized == "..":
        return None
    if len(normalized) >= 2 and normalized[1] == ":":
        return None
    return normalized


def _safe_target(root: Path, relative: str) -> Path:
    target = (root / Path(relative)).resolve()
    return ensure_within(root, target)


def ensure_within(root: Path, candidate: Path) -> Path:
    """Resolve a path and reject every candidate outside ``root``."""

    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise SourceSafetyError(f"路径越过暂存区：{candidate}") from exc
    return resolved_candidate


def _is_zip_symlink(member) -> bool:
    return (member.external_attr >> 16) & 0o170000 == 0o120000


def _locate_skill_root(root: Path) -> Path:
    marker = root / "SKILL.md"
    if marker.is_file():
        return root
    markers = sorted(root.rglob("SKILL.md"), key=lambda path: path.as_posix().casefold())
    if len(markers) == 1:
        return markers[0].parent
    return root
