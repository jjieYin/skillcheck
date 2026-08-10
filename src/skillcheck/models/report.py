from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from skillcheck.models.audit import CandidateMatch, Finding, LibraryAuditReport
from skillcheck.models.common import Decision
from skillcheck.models.review import AgentReview


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


class ScanRun(BaseModel):
    run_id: str
    started_at: datetime
    completed_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)
    index_revision: str
    capabilities: list[str] = Field(default_factory=list)
    skill_count: int = 0
    finding_count: int = 0
    status: str


class ReportBundle(BaseModel):
    report_id: str
    markdown: Path
    json_path: Path


class ScanOutcome(BaseModel):
    run: ScanRun
    skill_count: int
    group_counts: dict[str, int] = Field(default_factory=dict)
    high_priority_count: int = 0
    review: AgentReview
    report: ReportBundle
    modified_skill_paths: list[Path] = Field(default_factory=list)


__all__ = [
    "CheckReport",
    "LibraryAuditReport",
    "ReportBundle",
    "ScanOutcome",
    "ScanRun",
]
