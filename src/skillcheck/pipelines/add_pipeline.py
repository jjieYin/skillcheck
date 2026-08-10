from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from skillcheck.installation.executor import InstallationExecutor
from skillcheck.installation.planner import InstallationPlanner
from skillcheck.models import CheckReport, InstallationPlan
from skillcheck.models.review import AgentReview


class AddRequest(BaseModel):
    source: str
    targets: list[str] = Field(default_factory=list)
    target_paths: list[Path] = Field(default_factory=list)
    review: str = "none"
    top_k: int | None = None
    confirmed: bool = False


@dataclass(frozen=True)
class PreparedAdd:
    report: CheckReport
    plan: InstallationPlan
    paths: Any = None
    agent_review: AgentReview | None = None


class AddPipeline:
    def __init__(
        self,
        *,
        checker,
        planner: InstallationPlanner,
        executor: InstallationExecutor,
        review_pipeline=None,
    ) -> None:
        self.checker = checker
        self.planner = planner
        self.executor = executor
        self.review_pipeline = review_pipeline
        self.config: Any = None

    def prepare(self, request: AddRequest) -> PreparedAdd:
        use_direct_llm = request.review not in {"none", "codex", "claude"}
        check_kwargs: dict[str, bool | int] = {"use_llm": use_direct_llm}
        if request.top_k is not None:
            check_kwargs["top_k"] = request.top_k
        result = self.checker.check(request.source, **check_kwargs)
        plan = self.planner.create(
            result.report,
            targets=request.targets,
            target_paths=request.target_paths,
        )
        agent_review = None
        if self.review_pipeline is not None and request.review in {"codex", "claude"}:
            group = {
                "group_id": result.report.report_id,
                "relation": "MANUAL_REVIEW",
                "member_skill_ids": [candidate.skill.skill_id for candidate in result.report.candidates],
                "evidence": [finding.model_dump(mode="json") for finding in result.report.findings],
            }
            agent_review = self.review_pipeline.review(
                result.report.report_id,
                [group],
                request.review,
            )
        return PreparedAdd(
            report=result.report,
            plan=plan,
            paths=getattr(result, "paths", None),
            agent_review=agent_review,
        )

    def execute(self, prepared: PreparedAdd) -> list[Path]:
        self.planner.validate(prepared.plan, approval_token=prepared.plan.approval_token)
        return self.executor.execute(prepared.report, prepared.plan)

    def run(self, request: AddRequest) -> PreparedAdd | list[Path]:
        prepared = self.prepare(request)
        if not request.confirmed:
            return prepared
        return self.execute(prepared)
