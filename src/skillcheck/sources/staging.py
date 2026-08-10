from __future__ import annotations

from pathlib import Path

from skillcheck.sources.legacy import SourceLimits, SourceSafetyError, StagedSource
from skillcheck.sources.legacy import ensure_within as _ensure_within
from skillcheck.sources.legacy import stage_source as _stage_source

__all__ = ["SourceLimits", "SourceSafetyError", "StagedSource", "ensure_within", "stage_source"]


def ensure_within(root: Path, candidate: Path) -> Path:
    return _ensure_within(root, candidate)


def stage_source(
    source: str | Path,
    *,
    limits: SourceLimits | None = None,
    staging_parent: Path | str | None = None,
) -> StagedSource:
    return _stage_source(source, limits=limits, staging_parent=staging_parent)
