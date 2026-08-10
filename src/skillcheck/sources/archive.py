from __future__ import annotations

from pathlib import Path

from skillcheck.sources.legacy import SourceLimits, SourceSafetyError, StagedSource, _stage_zip


def stage_archive(
    source: str | Path,
    *,
    limits: SourceLimits | None = None,
    staging_parent: Path | str | None = None,
) -> StagedSource:
    archive = Path(source).expanduser()
    if archive.suffix.casefold() != ".zip":
        raise SourceSafetyError("source archive must be a ZIP file")
    return _stage_zip(str(source), archive.resolve(), limits or SourceLimits(), staging_parent)
