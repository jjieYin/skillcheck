"""Purely local command-line fallback for catalog governance checks."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from skillcheck.governance.analyzer import GovernanceAnalyzer
from skillcheck.governance.models import AnalyzeResult
from skillcheck.models.audit import AuditGroup, LibraryAuditReport
from skillcheck.reports import ReportWriter
from skillcheck.reports.writer import ReportPaths, make_audit_report_id

from .sync_pipeline import SyncPipeline


class LocalScanResult(BaseModel):
    """Artifacts produced without starting or delegating to an Agent."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    skill_count: int
    sync: dict[str, object]
    analysis: AnalyzeResult
    report: ReportPaths
    def json_payload(self) -> dict[str, object]:
        return {
            "skill_count": self.skill_count,
            "sync": self.sync,
            "analysis": self.analysis.model_dump(mode="json"),
            "report": {"markdown": str(self.report.markdown), "json": str(self.report.json)},
        }


class ScanPipeline:
    def __init__(
        self,
        sync: SyncPipeline,
        analyzer: GovernanceAnalyzer,
        reports: ReportWriter,
    ) -> None:
        self.sync = sync
        self.analyzer = analyzer
        self.reports = reports

    def run(self, paths: list[Path] | None = None) -> LocalScanResult:
        summary = self.sync.run(paths=paths or None)
        analysis = self.analyzer.analyze_library(limit=20)
        report = LibraryAuditReport(
            report_id=make_audit_report_id(analysis.run_id, [group.group_id for group in analysis.groups]),
            scope="local catalog",
            installation_count=analysis.summary.skills_considered,
            unique_skill_count=analysis.summary.skills_considered,
            groups=[
                AuditGroup(
                    group_id=group.group_id,
                    relation=group.relation.value,
                    member_skill_ids=group.member_skill_ids,
                    confidence=(f"{group.similarity:.3f}" if group.similarity is not None else "local-rule"),
                )
                for group in analysis.groups
            ],
            findings=analysis.deterministic_findings,
            capabilities=["local catalog sync", "deterministic governance analysis"],
            llm_used=False,
        )
        return LocalScanResult(
            skill_count=analysis.summary.skills_considered,
            sync=summary.model_dump(mode="json"),
            analysis=analysis,
            report=self.reports.write(report),
        )
