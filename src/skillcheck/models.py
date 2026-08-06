from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class Provider(StrEnum):
    CODEX = "codex"
    AGENTS = "agents"
    CLAUDE = "claude"
    CURSOR = "cursor"
    CUSTOM = "custom"


class Scope(StrEnum):
    GLOBAL = "global"
    PROJECT = "project"
    CUSTOM = "custom"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Decision(StrEnum):
    PASS = "PASS"
    DUPLICATE = "DUPLICATE"
    SIMILAR = "SIMILAR"
    CONFLICT = "CONFLICT"
    APPROVE = "APPROVE"
    MODIFY = "MODIFY"
    MERGE = "MERGE"
    VARIANT = "VARIANT"
    DEPRECATE = "DEPRECATE"
    REJECT = "REJECT"
    UNSAFE = "UNSAFE"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class SkillRecord(BaseModel):
    skill_id: str
    name: str
    description: str = ""
    root_path: Path
    provider: Provider | None = None
    scope: Scope | None = None
    body: str = ""
    content_hash: str
    tools: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    environments: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)


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


class ReviewAdvice(BaseModel):
    decision: Decision
    confidence: str
    target_skill_id: str | None = None
    evidence: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    llm_used: bool = False


class CheckReport(BaseModel):
    report_id: str
    source: str
    source_hash: str
    decision: Decision
    confidence: str
    blocking: bool
    findings: list[Finding] = Field(default_factory=list)
    candidates: list[CandidateMatch] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    llm_used: bool = False


class AuditGroup(BaseModel):
    group_id: str
    relation: str
    member_skill_ids: list[str]
    confidence: str
    same_points: list[str] = Field(default_factory=list)
    different_points: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class LibraryAuditReport(BaseModel):
    report_id: str
    scope: str
    installation_count: int
    unique_skill_count: int
    groups: list[AuditGroup] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    llm_used: bool = False
