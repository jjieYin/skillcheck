from __future__ import annotations

from pathlib import Path

from skillcheck.sources.legacy import SourceSafetyError, StagedSource


def stage_directory(source: str | Path) -> StagedSource:
    path = Path(source).expanduser()
    if not path.exists() or not path.is_dir():
        raise SourceSafetyError(f"source directory does not exist: {source}")
    return StagedSource(str(source), path.resolve())
