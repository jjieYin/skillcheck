from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from skillcheck.models.report import ReportBundle
from skillcheck.models.review import AgentReview
from skillcheck.reports.json_report import render_json
from skillcheck.reports.markdown import render_markdown
from skillcheck.reports.writer import _atomic_write, make_audit_report_id


class ReportDocument(BaseModel):
    report_id: str
    run_id: str
    skill_count: int
    installation_count: int
    unique_skill_count: int
    groups: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    agent_review: AgentReview | None = None


@dataclass(frozen=True)
class BaseReport:
    document: ReportDocument
    bundle: ReportBundle

    @property
    def report_id(self) -> str:
        return self.document.report_id

    def with_review(self, review: AgentReview) -> BaseReport:
        """Return the same local analysis with only the review layer replaced."""

        document = self.document.model_copy(update={"agent_review": review})
        return BaseReport(document=document, bundle=self.bundle)


class ReportBuilder:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def write_base(self, run, inventory, analysis) -> BaseReport:
        groups = [group.model_dump(mode="json") for group in getattr(analysis, "groups", [])]
        findings = [finding.model_dump(mode="json") for finding in getattr(analysis, "findings", [])]
        report_id = make_audit_report_id(run.run_id, [group["group_id"] for group in groups])
        document = ReportDocument(
            report_id=report_id,
            run_id=run.run_id,
            skill_count=len(inventory.unique_skills),
            installation_count=inventory.installation_count,
            unique_skill_count=len(inventory.unique_skills),
            groups=groups,
            findings=findings,
            capabilities=list(getattr(analysis, "capabilities", [])),
        )
        return BaseReport(document=document, bundle=self._write(document))

    def append_review(self, base: BaseReport, review: AgentReview) -> BaseReport:
        reviewed = base.with_review(review)
        return BaseReport(document=reviewed.document, bundle=self._write(reviewed.document))

    def _write(self, document: ReportDocument) -> ReportBundle:
        markdown_path = self.root / f"{document.report_id}.md"
        json_path = self.root / f"{document.report_id}.json"
        _atomic_write(markdown_path, render_markdown(document))
        _atomic_write(json_path, render_json(document))
        return ReportBundle(
            report_id=document.report_id,
            markdown=markdown_path,
            json_path=json_path,
        )
