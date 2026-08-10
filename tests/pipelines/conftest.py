from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from skillcheck.models.report import ScanOutcome, ScanRun
from skillcheck.models.review import AgentReview, ReviewStatus
from skillcheck.reports.builder import ReportBuilder


class FakeRuns:
    def __init__(self) -> None:
        self.completed: list[str] = []

    def start(self, scope):
        return ScanRun(
            run_id="run-001",
            started_at=datetime.now(UTC),
            scopes=scope.paths,
            index_revision="rev-1",
            status="running",
        )

    def complete(self, run_id: str, report_id: str) -> None:
        self.completed.append(f"{run_id}:{report_id}")


class FakeContext:
    def __init__(self, report_root: Path, skills: list[object]) -> None:
        self.runs = FakeRuns()
        self.discovery = SimpleNamespace(
            discover=lambda scope: SimpleNamespace(
                unique_skills=skills,
                installation_count=len(skills),
            )
        )
        self.parser = SimpleNamespace(
            parse_inventory=lambda inventory: SimpleNamespace(
                skills=inventory.unique_skills,
                vectors={},
                findings=[],
            )
        )
        self.skills = SimpleNamespace(replace_inventory=lambda skills, vectors: None)
        self.auditor = SimpleNamespace(
            audit=lambda skills, findings: SimpleNamespace(groups=[], findings=[], capabilities=["hash"])
        )
        self.reports = ReportBuilder(report_root)
        self.review_pipeline = SimpleNamespace(review=self.review)
        self.outcomes = SimpleNamespace(scan=self.scan_outcome)
        self._skills = skills

    def review(self, run_id: str, groups, mode: str) -> AgentReview:
        return AgentReview(
            review_id="review-001",
            run_id=run_id,
            agent=mode,
            status=ReviewStatus.SKIPPED,
            schema_version="1",
            full_text_shared=False,
        )

    def scan_outcome(self, run, inventory, analysis, review, final_report):
        return ScanOutcome(
            run=run,
            skill_count=len(inventory.unique_skills),
            group_counts={},
            review=review,
            report=final_report.bundle,
        )


@pytest.fixture
def skill_library(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    root.mkdir()
    (root / "one").mkdir()
    (root / "two").mkdir()
    (root / "one" / "SKILL.md").write_text("# one\n", encoding="utf-8")
    (root / "two" / "SKILL.md").write_text("# two\n", encoding="utf-8")
    return root


@pytest.fixture
def fake_context(tmp_path: Path, skill_library: Path) -> FakeContext:
    skills = [object(), object()]
    return FakeContext(tmp_path / "reports", skills)
