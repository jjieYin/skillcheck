from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from skillcheck.config import load_or_create_config
from skillcheck.installation.executor import InstallationExecutor
from skillcheck.installation.planner import InstallationPlanner
from skillcheck.models.report import ScanOutcome, ScanRun
from skillcheck.models.review import AgentReview, ReviewStatus
from skillcheck.pipelines.add_pipeline import AddPipeline
from skillcheck.pipelines.review_pipeline import ReviewPipeline
from skillcheck.pipelines.scan_pipeline import ScanPipeline
from skillcheck.reports import ReportBuilder
from skillcheck.reviewers.claude import ClaudeReviewAdapter
from skillcheck.reviewers.codex import CodexReviewAdapter
from skillcheck.reviewers.packet import build_packets
from skillcheck.reviewers.registry import ReviewRegistry
from skillcheck.reviewers.validation import validate_agent_output
from skillcheck.service import SkillCheckService, build_service


@dataclass(frozen=True)
class ApplicationContext:
    """Dependencies shared by command handlers.

    The concrete services are introduced by later pipeline tasks. Keeping this
    small container in place lets commands receive dependencies without
    importing global singletons.
    """

    config: Any
    terminal: Any


class LegacyRunStore:
    def start(self, scope) -> ScanRun:
        return ScanRun(
            run_id=f"run-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}",
            started_at=datetime.now(UTC),
            scopes=list(scope.paths),
            index_revision="local",
            status="running",
        )

    def complete(self, run_id: str, report_id: str) -> None:
        return None


class LegacyDiscovery:
    def __init__(self, service: SkillCheckService) -> None:
        self.service = service

    def discover(self, scope):
        for value in scope.paths:
            path = Path(value).expanduser()
            if path not in self.service.config.extra_paths:
                self.service.config.extra_paths.append(path)
        cwd = Path(scope.paths[0]) if scope.paths else None
        inventory = self.service.scan(cwd=cwd).inventory
        return inventory


class LegacyParser:
    def __init__(self, service: SkillCheckService) -> None:
        self.service = service

    def parse_inventory(self, inventory):
        skills = inventory.unique_skills
        vectors = {
            row.skill_id: row.vector
            for row in self.service.store.get_vector_rows(model=self.service.embedding.model_id)
        }
        findings = {
            skill.skill_id: self.service._findings(skill)
            for skill in skills
        }
        return type("ParsedInventory", (), {
            "skills": skills,
            "vectors": vectors,
            "findings": findings,
        })()


class LegacySkills:
    def replace_inventory(self, skills, vectors) -> None:
        return None


class LegacyAuditor:
    def __init__(self, service: SkillCheckService) -> None:
        self.service = service

    def audit(self, skills, findings):
        if not skills:
            return type(
                "EmptyAudit",
                (),
                {"groups": [], "findings": [], "capabilities": ["builtin-validator"]},
            )()
        return self.service.audit(use_llm=False).audit


class NoAgentReview:
    def review(self, run_id: str, groups, mode: str) -> AgentReview:
        return AgentReview(
            review_id=f"review-{run_id}",
            run_id=run_id,
            agent=mode,
            status=ReviewStatus.SKIPPED,
            schema_version="1",
            full_text_shared=False,
        )


def build_review_pipeline(config) -> ReviewPipeline:
    registry = ReviewRegistry(
        [
            CodexReviewAdapter(timeout_seconds=config.review.timeout_seconds),
            ClaudeReviewAdapter(timeout_seconds=config.review.timeout_seconds),
        ]
    )
    return ReviewPipeline(
        registry,
        validator=validate_agent_output,
        packet_builder=lambda groups: build_packets(
            groups,
            max_groups=config.review.max_groups_per_request,
            allow_full_text=config.review.allow_full_text,
        ),
    )


class OutcomeFactory:
    def scan(self, run, inventory, analysis, review, final_report) -> ScanOutcome:
        return ScanOutcome(
            run=run,
            skill_count=len(inventory.unique_skills),
            group_counts={},
            high_priority_count=sum(
                1
                for finding in getattr(analysis, "findings", [])
                if getattr(finding.severity, "value", finding.severity) in {"high", "critical"}
            ),
            review=review,
            report=final_report.bundle,
        )


def build_scan_pipeline(config_path: Path | str | None = None) -> ScanPipeline:
    config = load_or_create_config(config_path)
    service = build_service(config)
    context = type("ScanContext", (), {})()
    context.config = config
    context.service = service
    context.runs = LegacyRunStore()
    context.discovery = LegacyDiscovery(service)
    context.parser = LegacyParser(service)
    context.skills = LegacySkills()
    context.auditor = LegacyAuditor(service)
    context.reports = ReportBuilder(config.reports_path)
    context.review_pipeline = build_review_pipeline(config)
    context.outcomes = OutcomeFactory()
    pipeline = ScanPipeline(context)
    pipeline.config = config
    return pipeline


def build_add_pipeline(config_path: Path | str | None = None) -> AddPipeline:
    config = load_or_create_config(config_path)
    service = build_service(config)
    pipeline = AddPipeline(
        checker=service,
        planner=InstallationPlanner(staging_parent=config.staging_path),
        executor=InstallationExecutor(),
        review_pipeline=build_review_pipeline(config),
    )
    pipeline.config = config
    return pipeline
