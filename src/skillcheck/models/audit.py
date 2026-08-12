from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from skillcheck.models.common import Decision, Severity
from skillcheck.models.skill import SkillRecord


class Relation(StrEnum):
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    HIGH_OVERLAP = "HIGH_OVERLAP"
    VARIANT_GROUP = "VARIANT_GROUP"
    CONFLICT_GROUP = "CONFLICT_GROUP"
    QUALITY_ISSUE = "QUALITY_ISSUE"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class Evidence(BaseModel):
    kind: str
    source_skill_id: str
    target_skill_id: str | None = None
    value: str
    excerpt: str | None = None
    excerpt_hash: str | None = None
    sensitive: bool = False


class GovernanceGroup(BaseModel):
    group_id: str
    relation: Relation
    member_skill_ids: list[str]
    similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)
    rule_suggestion: str
    requires_semantic_review: bool


class Finding(BaseModel):
    rule_id: str
    severity: Severity
    message: str
    evidence_path: str | None = None
    remediation: str


class CandidateMatch(BaseModel):
    skill: SkillRecord
    similarity: float
    relation: Decision = Decision.SIMILAR
    same_points: list[str] = Field(default_factory=list)
    different_points: list[str] = Field(default_factory=list)


class AuditGroup(BaseModel):
    group_id: str
    relation: str
    member_skill_ids: list[str]
    confidence: str
    same_points: list[str] = Field(default_factory=list)
    different_points: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def set_mirror_recommendation(self) -> "AuditGroup":
        if self.relation == "MIRRORED_COPY":
            self.recommendations = ["合理跨作用域分发；可选择建立只监测同步组"]
        return self


class LibraryAuditReport(BaseModel):
    report_id: str
    scope: str
    installation_count: int
    unique_skill_count: int
    exact_duplicates: int = 0
    mirrored_copy_groups: int = 0
    sync_groups_total: int = 0
    sync_groups_drifted: int = 0
    groups: list[AuditGroup] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    llm_used: bool = False
