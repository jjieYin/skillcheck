from enum import StrEnum

from pydantic import BaseModel, Field

from skillcheck.models.common import Decision


class ReviewStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentDecision(BaseModel):
    group_id: str
    decision: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    canonical_skill: str | None = None
    recommendations: list[str] = Field(default_factory=list)


class AgentReview(BaseModel):
    review_id: str
    run_id: str
    agent: str
    status: ReviewStatus
    schema_version: str
    full_text_shared: bool
    decisions: list[AgentDecision] = Field(default_factory=list)
    error: str | None = None


class ReviewAdvice(BaseModel):
    decision: Decision
    confidence: str
    target_skill_id: str | None = None
    evidence: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    llm_used: bool = False
