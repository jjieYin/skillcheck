"""Skill source adapters with v1-compatible exports."""

from skillcheck.sources.archive import stage_archive
from skillcheck.sources.github import stage_github
from skillcheck.sources.local import stage_directory
from skillcheck.sources.legacy import SourceLimits, SourceSafetyError, StagedSource
from skillcheck.sources.staging import stage_source
from skillcheck.sources.legacy import subprocess

__all__ = [
    "SourceLimits",
    "SourceSafetyError",
    "StagedSource",
    "stage_archive",
    "stage_directory",
    "stage_github",
    "stage_source",
]
