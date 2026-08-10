"""Skill source adapters with v1-compatible exports."""

from skillcheck.sources.archive import stage_archive
from skillcheck.sources.github import stage_github
from skillcheck.sources.legacy import (
    SourceLimits,
    SourceSafetyError,
    StagedSource,
    ensure_within,
    subprocess,
)
from skillcheck.sources.local import stage_directory
from skillcheck.sources.staging import stage_source

__all__ = [
    "SourceLimits",
    "SourceSafetyError",
    "StagedSource",
    "ensure_within",
    "stage_archive",
    "stage_directory",
    "stage_github",
    "stage_source",
    "subprocess",
]
