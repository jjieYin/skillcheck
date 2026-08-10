from __future__ import annotations

from pathlib import Path

from skillcheck.sources.legacy import (
    SourceLimits,
    SourceSafetyError,
    StagedSource,
    stage_source as _stage_source,
)


def stage_source(
    source: str | Path,
    *,
    limits: SourceLimits | None = None,
    staging_parent: Path | str | None = None,
) -> StagedSource:
    return _stage_source(source, limits=limits, staging_parent=staging_parent)
