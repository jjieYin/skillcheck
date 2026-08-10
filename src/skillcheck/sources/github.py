from __future__ import annotations

from pathlib import Path

from skillcheck.sources.legacy import SourceSafetyError, StagedSource, _stage_github


def stage_github(source: str, *, staging_parent: Path | str | None = None) -> StagedSource:
    if not source.startswith("https://"):
        raise SourceSafetyError("source must be an HTTPS GitHub URL")
    return _stage_github(source, staging_parent)
