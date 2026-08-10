from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class GovernanceDecision(StrEnum):
    KEEP_BOTH = "KEEP_BOTH"
    MERGE = "MERGE"
    DEPRECATE = "DEPRECATE"
    DELETE_DUPLICATE = "DELETE_DUPLICATE"
    RENAME = "RENAME"
    REWRITE_BOUNDARY = "REWRITE_BOUNDARY"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class GroupDecision(BaseModel):
    group_id: str
    decision: GovernanceDecision
    canonical_skill: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=4000)
    recommendations: list[str] = Field(default_factory=list, max_length=20)


class SavedReview(BaseModel):
    review_id: str
    run_id: str
    revision: str
    decisions: list[GroupDecision]
    markdown_path: Path
    json_path: Path
