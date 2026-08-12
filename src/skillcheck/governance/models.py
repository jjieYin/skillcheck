from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from skillcheck.models.audit import Finding


class AnalyzeMode(StrEnum):
    LIBRARY = "library"
    SOURCE = "source"


class Relation(StrEnum):
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    MIRRORED_COPY = "MIRRORED_COPY"
    SYNC_GROUP_DRIFT = "SYNC_GROUP_DRIFT"
    HIGH_OVERLAP_CANDIDATE = "HIGH_OVERLAP_CANDIDATE"
    CONFLICT_CANDIDATE = "CONFLICT_CANDIDATE"
    VARIANT_CANDIDATE = "VARIANT_CANDIDATE"
    QUALITY_ISSUE = "QUALITY_ISSUE"
    SECURITY_ISSUE = "SECURITY_ISSUE"


class CandidateGroupSummary(BaseModel):
    group_id: str
    relation: Relation
    member_skill_ids: list[str]
    similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    requires_agent_judgment: bool


class AnalyzeSummary(BaseModel):
    skills_considered: int = 0
    exact_duplicates: int = 0
    mirrored_copy_groups: int = 0
    sync_groups_total: int = 0
    sync_groups_drifted: int = 0
    overlap_candidates: int = 0
    conflict_candidates: int = 0
    variant_candidates: int = 0
    quality_issues: int = 0
    security_issues: int = 0


class AnalyzeResult(BaseModel):
    run_id: str
    mode: AnalyzeMode
    revision: str
    stale: bool
    summary: AnalyzeSummary
    groups: list[CandidateGroupSummary]
    deterministic_findings: list[Finding]
    next_tool: str | None


class EvidenceSkill(BaseModel):
    skill_id: str
    snapshot_id: str
    provider: str
    scope: str
    project_path: str | None
    root_path: str
    name: str
    description: str
    content_hash: str
    tools: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    environments: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    body: str | None = None


class EvidencePage(BaseModel):
    run_id: str
    group_id: str
    revision: str
    stale: bool
    page: int
    page_count: int
    members: list[EvidenceSkill]
    shared_capabilities: list[str]
    different_capabilities: list[str]


class SourcePreflight(BaseModel):
    """The bounded, local evidence associated with a staged installation source."""

    run_id: str
    source: str
    source_hash: str
    created_at: datetime
    expires_at: datetime
    deterministic_blockers: list[Finding] = Field(default_factory=list)


class SyncPolicy(StrEnum):
    MONITOR_ONLY = "monitor_only"


class SyncMemberRole(StrEnum):
    AUTHORITY = "authority"
    MIRROR = "mirror"


class SyncGroupStatus(StrEnum):
    IN_SYNC = "IN_SYNC"
    DRIFTED = "DRIFTED"
    DIVERGED = "DIVERGED"
    BROKEN = "BROKEN"
    INVALID_MEMBER = "INVALID_MEMBER"


class SyncGroupMember(BaseModel):
    skill_id: str
    role: SyncMemberRole
    baseline_snapshot_id: str
    baseline_content_hash: str


class SyncGroup(BaseModel):
    group_id: str
    name: str
    authority_skill_id: str
    policy: SyncPolicy = SyncPolicy.MONITOR_ONLY
    baseline_revision: str
    status: SyncGroupStatus
    members: list[SyncGroupMember]
