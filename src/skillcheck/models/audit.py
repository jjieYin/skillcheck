from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from skillcheck.core.features import PairSignals
from skillcheck.models.common import Decision, Severity
from skillcheck.models.skill import SkillRecord


class Relation(StrEnum):
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    BEHAVIOR_DUPLICATE_CANDIDATE = "BEHAVIOR_DUPLICATE_CANDIDATE"
    IMPLEMENTATION_VARIANT_CANDIDATE = "IMPLEMENTATION_VARIANT_CANDIDATE"
    HIGH_OVERLAP = "HIGH_OVERLAP"
    CONTAINMENT_CANDIDATE = "CONTAINMENT_CANDIDATE"
    CONSTRAINT_MISMATCH_CANDIDATE = "CONSTRAINT_MISMATCH_CANDIDATE"
    VARIANT_GROUP = "VARIANT_GROUP"
    CONFLICT_GROUP = "CONFLICT_GROUP"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    QUALITY_ISSUE = "QUALITY_ISSUE"


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


class SkillFinding(BaseModel):
    skill_id: str
    finding: Finding


class PairEvidence(BaseModel):
    source_skill_id: str
    target_skill_id: str
    relation: str
    signals: PairSignals
    confidence: str
    evidence: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    signals_version: str = "v2"
    package_hash_equal: bool | None = None
    behavior_hash_equal: bool | None = None
    execution_hash_equal: bool | None = None
    execution_equivalent: bool | None = None
    channel_scores: dict[str, float | None] = Field(default_factory=dict)
    procedure_coverage_left: float | None = None
    procedure_coverage_right: float | None = None
    constraint_polarity_mismatch: bool | None = None
    relation_score: float | None = Field(default=None, ge=0.0, le=1.0)
    vectorizer_descriptor: dict[str, object] | None = None
    vectorizer_signature: str | None = None
    threshold_profile: str | None = None
    vectorizer_degraded: str | None = None

    @model_validator(mode="after")
    def expose_v2_signal_summary(self) -> "PairEvidence":
        signals = self.signals
        self.package_hash_equal = (
            signals.package_hash_equal if self.package_hash_equal is None else self.package_hash_equal
        )
        self.behavior_hash_equal = (
            signals.behavior_hash_equal if self.behavior_hash_equal is None else self.behavior_hash_equal
        )
        self.execution_hash_equal = (
            signals.execution_hash_equal
            if self.execution_hash_equal is None
            else self.execution_hash_equal
        )
        self.execution_equivalent = (
            signals.execution_equivalent
            if self.execution_equivalent is None
            else self.execution_equivalent
        )
        self.procedure_coverage_left = (
            signals.procedure_coverage_left
            if self.procedure_coverage_left is None
            else self.procedure_coverage_left
        )
        self.procedure_coverage_right = (
            signals.procedure_coverage_right
            if self.procedure_coverage_right is None
            else self.procedure_coverage_right
        )
        self.constraint_polarity_mismatch = (
            signals.constraint_polarity_mismatch
            if self.constraint_polarity_mismatch is None
            else self.constraint_polarity_mismatch
        )
        if not self.channel_scores:
            self.channel_scores = {
                "activation_lexical": signals.activation_lexical_similarity,
                "procedure_coverage_left": signals.procedure_coverage_left,
                "procedure_coverage_right": signals.procedure_coverage_right,
                "constraint_action": signals.constraint_action_similarity,
                "hashed_lexical": signals.hashed_lexical_similarity,
                "activation_dense": signals.activation_dense_similarity,
                "procedure_dense_left": signals.procedure_dense_coverage_left,
                "procedure_dense_right": signals.procedure_dense_coverage_right,
            }
        if self.relation_score is None:
            self.relation_score = self.similarity
        return self

    @property
    def pair(self) -> tuple[str, str]:
        return self.source_skill_id, self.target_skill_id

    @property
    def similarity(self) -> float:
        value = (
            self.signals.relation_score
            if self.signals.relation_score is not None
            else self.signals.semantic_similarity
            or self.signals.hashed_lexical_similarity
            or self.signals.activation_lexical_similarity
            or 0.0
        )
        return min(1.0, max(0.0, float(value)))


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
    pair_evidence: list[PairEvidence] = Field(default_factory=list)
    min_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    max_similarity: float | None = Field(default=None, ge=0.0, le=1.0)

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
