from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ReviewMode(StrEnum):
    NONE = "none"
    CODEX = "codex"
    CLAUDE = "claude"


class ScanScope(BaseModel):
    paths: list[str] = Field(default_factory=list)


class ScanPipeline:
    def __init__(self, context) -> None:
        self.context = context

    def run(self, scope: ScanScope, review: ReviewMode):
        run = self.context.runs.start(scope)
        inventory = self.context.discovery.discover(scope)
        parsed = self.context.parser.parse_inventory(inventory)
        self.context.skills.replace_inventory(parsed.skills, parsed.vectors)
        analysis = self.context.auditor.audit(parsed.skills, parsed.findings)
        base_report = self.context.reports.write_base(run, inventory, analysis)
        agent_review = self.context.review_pipeline.review(run.run_id, analysis.groups, review.value)
        final_report = self.context.reports.append_review(base_report, agent_review)
        self.context.runs.complete(run.run_id, final_report.report_id)
        return self.context.outcomes.scan(run, inventory, analysis, agent_review, final_report)
