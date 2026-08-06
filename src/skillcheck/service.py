from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from skillcheck.audit import AuditResult, LibraryAuditor
from skillcheck.config import AppConfig
from skillcheck.decisions import RuleDecision, RuleDecisionEngine
from skillcheck.discovery import Inventory, discover_skills
from skillcheck.embeddings import EmbeddingBackend, skill_embedding_text
from skillcheck.llm import AuditGroupReviewInput, LLMReviewer, LLMReviewInput
from skillcheck.models import (
    CandidateMatch,
    CheckReport,
    Decision,
    Finding,
    LibraryAuditReport,
    Severity,
    SkillRecord,
)
from skillcheck.parser import parse_skill
from skillcheck.reports import ReportPaths, ReportWriter, make_audit_report_id, make_check_report_id
from skillcheck.retrieval import cosine_top_k
from skillcheck.sources import SourceLimits, stage_source
from skillcheck.store import SkillStore
from skillcheck.validators import BuiltinValidator


@dataclass(frozen=True)
class ScanResult:
    inventory: Inventory

    @property
    def installation_count(self) -> int:
        return self.inventory.installation_count

    @property
    def unique_skill_count(self) -> int:
        return len(self.inventory.unique_skills)


@dataclass(frozen=True)
class CheckResult:
    report: CheckReport
    paths: ReportPaths


@dataclass(frozen=True)
class AuditServiceResult:
    report: LibraryAuditReport
    paths: ReportPaths
    audit: AuditResult


class SkillCheckService:
    def __init__(
        self,
        *,
        config: AppConfig,
        store: SkillStore,
        embedding: EmbeddingBackend,
        validator: BuiltinValidator,
        skillspector,
        reviewer: LLMReviewer | None,
        report_writer: ReportWriter,
    ) -> None:
        self.config = config
        self.store = store
        self.embedding = embedding
        self.validator = validator
        self.skillspector = skillspector
        self.reviewer = reviewer
        self.report_writer = report_writer
        self.decision_engine = RuleDecisionEngine(config.thresholds)

    def scan(self, *, cwd: Path | str | None = None) -> ScanResult:
        inventory = discover_skills(self.config, cwd=cwd)
        skills = inventory.unique_skills
        existing: dict[str, np.ndarray] = {
            row.skill_id: row.vector for row in self.store.get_vector_rows(model=self.embedding.model_id)
        }
        vectors: dict[str, np.ndarray] = dict(existing)
        to_embed = [skill for skill in skills if self.store.needs_embedding(skill, self.embedding.model_id)]
        if to_embed:
            encoded = self.embedding.encode([skill_embedding_text(skill) for skill in to_embed])
            if len(encoded) != len(to_embed):
                raise RuntimeError("embedding backend returned an unexpected row count")
            vectors.update({skill.skill_id: encoded[index] for index, skill in enumerate(to_embed)})
        self.store.replace_inventory(skills, vectors, model=self.embedding.model_id)
        return ScanResult(inventory)

    def list_skills(self, *, provider=None, duplicates: bool = False) -> list[SkillRecord]:
        skills = self.store.list_skills(provider=provider)
        if not duplicates:
            return skills
        by_hash: dict[str, list[SkillRecord]] = {}
        for skill in skills:
            by_hash.setdefault(skill.content_hash, []).append(skill)
        return [skill for group in by_hash.values() if len(group) > 1 for skill in group]

    def audit(
        self,
        *,
        path: Path | str | None = None,
        provider=None,
        use_llm: bool = True,
        refresh: bool = False,
    ) -> AuditServiceResult:
        if refresh:
            self.scan()
        skills = self.store.list_skills()
        if not skills:
            raise RuntimeError("Skill index is empty; run skillcheck scan first")
        vector_rows = self.store.get_vector_rows(model=self.embedding.model_id)
        vectors: dict[str, np.ndarray] = {row.skill_id: row.vector for row in vector_rows}
        findings = {skill.skill_id: self._findings(skill) for skill in skills}
        audit = LibraryAuditor(self.config.thresholds.top_k, self.decision_engine).audit(
            skills,
            vectors,
            findings=findings,
            provider=provider,
            root_path=path,
        )
        capabilities = ["builtin-validator", "library-audit", f"embedding:{self.embedding.model_id}"]
        if not vector_rows:
            capabilities.append("embedding-degraded")
        if self.skillspector is not None:
            capabilities.append("skillspector" if self.skillspector.available() else "skillspector-unavailable")
        llm_used = False
        if use_llm and self.reviewer is not None:
            group_skills = {skill.skill_id: skill for skill in skills}
            for group in audit.groups:
                if group.relation in {"EXACT_DUPLICATE", "QUALITY_ISSUE"}:
                    continue
                advice = self.reviewer.review_audit_group(
                    AuditGroupReviewInput(
                        group=group,
                        skills=[self._llm_safe_skill(group_skills[item]) for item in group.member_skill_ids if item in group_skills],
                        findings=[finding for values in findings.values() for finding in values],
                    )
                )
                if advice.llm_used:
                    llm_used = True
                    group.recommendations.extend(
                        f"LLM 建议（{advice.decision.value}）：{recommendation}"
                        for recommendation in advice.recommendations
                    )
            capabilities.append("llm-review" if llm_used else "llm-review-degraded")
        elif use_llm:
            capabilities.append("llm-disabled")
        scope = _scope_text(path, provider)
        report = LibraryAuditReport(
            report_id=make_audit_report_id(scope, [group.group_id for group in audit.groups]),
            scope=scope,
            installation_count=audit.installation_count,
            unique_skill_count=audit.unique_skill_count,
            groups=audit.groups,
            findings=audit.findings,
            capabilities=capabilities,
            llm_used=llm_used,
        )
        paths = self.report_writer.write(report)
        return AuditServiceResult(report=report, paths=paths, audit=audit)

    def check(
        self,
        source: str | Path,
        *,
        use_llm: bool = True,
        top_k: int | None = None,
    ) -> CheckResult:
        self.config.staging_path.mkdir(parents=True, exist_ok=True)
        staged = stage_source(source, limits=SourceLimits(), staging_parent=self.config.staging_path)
        try:
            incoming = parse_skill(staged.root)
            findings = self._findings(incoming)
            skills = {skill.skill_id: skill for skill in self.store.list_skills()}
            vector_rows = self.store.get_vector_rows(model=self.embedding.model_id)
            query_vector = self.embedding.encode([skill_embedding_text(incoming)])[0]
            candidates = []
            for score in cosine_top_k(query_vector, [(row.skill_id, row.vector) for row in vector_rows], top_k or self.config.thresholds.top_k):
                if score.skill_id in skills:
                    candidates.append(CandidateMatch(skill=skills[score.skill_id], similarity=score.similarity))
            deterministic = self._deterministic_check(incoming, candidates, findings)
            capabilities = ["builtin-validator", f"embedding:{self.embedding.model_id}"]
            if self.skillspector is not None:
                capabilities.append("skillspector" if self.skillspector.available() else "skillspector-unavailable")
            advice = None
            final_decision = deterministic.decision
            confidence = deterministic.confidence
            recommendations = list(deterministic.recommendations)
            llm_used = False
            if use_llm and self.reviewer is not None and deterministic.decision != Decision.UNSAFE:
                advice = self.reviewer.review(
                    LLMReviewInput(
                        new_skill=self._llm_safe_skill(incoming),
                        candidates=candidates,
                        findings=findings,
                    )
                )
                recommendations.extend(advice.recommendations)
                if advice.llm_used:
                    final_decision = advice.decision
                    confidence = advice.confidence
                    llm_used = True
                    capabilities.append("llm-review")
                else:
                    final_decision = Decision.MANUAL_REVIEW
                    capabilities.append("llm-review-degraded")
            elif use_llm:
                capabilities.append("llm-disabled")
            report = CheckReport(
                report_id=make_check_report_id(incoming.content_hash),
                source=str(source),
                source_hash=incoming.content_hash,
                decision=final_decision,
                confidence=confidence,
                blocking=_is_blocking(final_decision),
                findings=findings,
                candidates=candidates,
                recommendations=_dedupe(recommendations),
                capabilities=capabilities,
                llm_used=llm_used,
            )
            paths = self.report_writer.write(report)
            return CheckResult(report=report, paths=paths)
        finally:
            staged.close()

    def _deterministic_check(
        self,
        incoming: SkillRecord,
        candidates: list[CandidateMatch],
        findings: list[Finding],
    ) -> RuleDecision:
        severe = [finding for finding in findings if finding.severity in {Severity.HIGH, Severity.CRITICAL}]
        if severe:
            return RuleDecision(
                Decision.UNSAFE,
                "high",
                True,
                [finding.message for finding in severe],
                [finding.remediation for finding in severe],
            )
        if not candidates:
            return RuleDecision(
                Decision.PASS,
                "low",
                False,
                ["没有可用的现有 Skill 候选。"],
                ["可以进入人工确认或安装流程。"],
            )
        return self.decision_engine.decide(incoming, candidates[0], findings)

    def _findings(self, skill: SkillRecord) -> list[Finding]:
        findings = self.validator.scan(skill.root_path, skill)
        if self.skillspector is not None:
            findings.extend(self.skillspector.scan(skill.root_path))
        return findings

    def _llm_safe_skill(self, skill: SkillRecord) -> SkillRecord:
        if self.config.llm.allow_full_text:
            return skill
        return skill.model_copy(update={"body": "[body omitted by local privacy policy]"})


def build_service(config: AppConfig, *, reviewer: LLMReviewer | None = None) -> SkillCheckService:
    from skillcheck.embeddings import backend_from_config
    from skillcheck.skillspector import SkillSpectorAdapter

    embedding = backend_from_config(config.embedding)
    scanner = (
        SkillSpectorAdapter(config.security.skill_spector_command or "skillspector", config.security.timeout_seconds)
        if config.security.enabled
        else None
    )
    return SkillCheckService(
        config=config,
        store=SkillStore(config.index_path),
        embedding=embedding,
        validator=BuiltinValidator(),
        skillspector=scanner,
        reviewer=reviewer,
        report_writer=ReportWriter(config.reports_path),
    )


def _is_blocking(decision: Decision) -> bool:
    return decision in {
        Decision.DUPLICATE,
        Decision.CONFLICT,
        Decision.UNSAFE,
        Decision.MERGE,
        Decision.DEPRECATE,
        Decision.REJECT,
        Decision.MANUAL_REVIEW,
    }


def _scope_text(path, provider) -> str:
    if path:
        return f"path:{path}"
    if provider:
        return f"provider:{provider}"
    return "all"


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
