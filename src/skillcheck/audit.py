from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from skillcheck.decisions import RuleDecision, RuleDecisionEngine
from skillcheck.models import AuditGroup, CandidateMatch, Finding, Provider, Severity, SkillRecord
from skillcheck.retrieval import cosine_top_k


@dataclass(frozen=True)
class AuditScope:
    provider: Provider | str | None = None
    root_path: Path | None = None


@dataclass(frozen=True)
class PairEvidence:
    pair: tuple[str, str]
    relation: str
    confidence: str
    similarity: float
    evidence: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()


@dataclass
class AuditResult:
    groups: list[AuditGroup] = field(default_factory=list)
    compared_pairs: list[tuple[str, str]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    installation_count: int = 0
    unique_skill_count: int = 0


class LibraryAuditor:
    def __init__(self, top_k: int = 5, decision_engine: RuleDecisionEngine | None = None) -> None:
        self.top_k = max(1, top_k)
        self.decision_engine = decision_engine or RuleDecisionEngine()

    def audit(
        self,
        skills: Iterable[SkillRecord],
        vectors: dict[str, Iterable[float] | np.ndarray],
        *,
        findings: list[Finding] | dict[str, list[Finding]],
        provider: Provider | str | None = None,
        root_path: Path | str | None = None,
        scope: AuditScope | None = None,
    ) -> AuditResult:
        if scope is not None:
            provider = scope.provider if provider is None else provider
            root_path = scope.root_path if root_path is None else root_path
        selected = self._filter_skills(list(skills), provider=provider, root_path=root_path)
        selected.sort(key=lambda skill: skill.skill_id)
        by_id = {skill.skill_id: skill for skill in selected}
        result = AuditResult(
            installation_count=len(selected),
            unique_skill_count=len({skill.content_hash for skill in selected}),
        )
        findings_by_skill = _findings_by_skill(findings)
        result.findings.extend(_global_findings(findings))

        exact_groups = self._exact_groups(selected)
        exact_member_ids: set[str] = set()
        for member_ids in exact_groups:
            exact_member_ids.update(member_ids)
            result.groups.append(
                AuditGroup(
                    group_id=_group_id("EXACT_DUPLICATE", member_ids),
                    relation="EXACT_DUPLICATE",
                    member_skill_ids=member_ids,
                    confidence="high",
                    same_points=["content hashes are identical"],
                    recommendations=["保留一个权威副本，删除或停用其余重复 Skill。"],
                )
            )

        for skill in selected:
            if skill.skill_id not in vectors:
                finding = Finding(
                    rule_id="AUDIT001",
                    severity=Severity.INFO,
                    message=f"Skill {skill.skill_id} has no embedding vector; semantic audit is degraded.",
                    evidence_path="SKILL.md",
                    remediation="Run skillcheck scan --refresh or configure an embedding backend.",
                )
                result.findings.append(finding)

        vector_rows = [
            (skill_id, np.asarray(vector, dtype=np.float32))
            for skill_id, vector in vectors.items()
            if skill_id in by_id
        ]
        pair_evidence: dict[tuple[str, str], PairEvidence] = {}
        for skill in selected:
            vector = vectors.get(skill.skill_id)
            if vector is None:
                continue
            candidates = cosine_top_k(np.asarray(vector, dtype=np.float32), vector_rows, self.top_k + 1)
            for candidate in candidates:
                if candidate.skill_id == skill.skill_id or candidate.skill_id not in by_id:
                    continue
                if skill.content_hash == by_id[candidate.skill_id].content_hash:
                    continue
                pair = tuple(sorted((skill.skill_id, candidate.skill_id)))
                if pair in pair_evidence:
                    continue
                target = by_id[candidate.skill_id]
                decision = self.decision_engine.decide(
                    skill,
                    CandidateMatch(skill=target, similarity=candidate.similarity),
                    [*findings_by_skill.get(skill.skill_id, []), *findings_by_skill.get(target.skill_id, [])],
                )
                if decision.decision.value == "PASS":
                    pair_evidence[pair] = PairEvidence(
                        pair,
                        "PASS",
                        decision.confidence,
                        candidate.similarity,
                        tuple(decision.evidence),
                        tuple(decision.recommendations),
                    )
                else:
                    pair_evidence[pair] = PairEvidence(
                        pair,
                        _audit_relation(decision),
                        decision.confidence,
                        candidate.similarity,
                        tuple(decision.evidence),
                        tuple(decision.recommendations),
                    )

        result.compared_pairs = sorted(pair_evidence)
        result.groups.extend(_groups_from_pairs(pair_evidence))
        result.groups.extend(_quality_groups(selected, findings_by_skill, result.groups))
        result.groups.sort(key=lambda group: (_relation_priority(group.relation), group.member_skill_ids))
        return result

    @staticmethod
    def _filter_skills(
        skills: list[SkillRecord],
        *,
        provider: Provider | str | None,
        root_path: Path | str | None,
    ) -> list[SkillRecord]:
        provider_value = provider.value if isinstance(provider, Provider) else str(provider) if provider else None
        root = Path(root_path).expanduser().resolve() if root_path else None
        selected: list[SkillRecord] = []
        for skill in skills:
            if provider_value and (skill.provider is None or skill.provider.value != provider_value):
                continue
            if root:
                try:
                    skill.root_path.resolve().relative_to(root)
                except ValueError:
                    continue
            selected.append(skill)
        return selected

    @staticmethod
    def _exact_groups(skills: list[SkillRecord]) -> list[list[str]]:
        by_hash: dict[str, list[str]] = defaultdict(list)
        for skill in skills:
            by_hash[skill.content_hash].append(skill.skill_id)
        return [sorted(ids) for ids in by_hash.values() if len(ids) > 1]


def _findings_by_skill(findings: list[Finding] | dict[str, list[Finding]]) -> dict[str, list[Finding]]:
    return findings if isinstance(findings, dict) else {}


def _global_findings(findings: list[Finding] | dict[str, list[Finding]]) -> list[Finding]:
    return findings if isinstance(findings, list) else [item for values in findings.values() for item in values]


def _audit_relation(decision: RuleDecision) -> str:
    return {
        "DUPLICATE": "EXACT_DUPLICATE",
        "SIMILAR": "HIGH_OVERLAP",
        "VARIANT": "VARIANT_GROUP",
        "CONFLICT": "CONFLICT_GROUP",
        "UNSAFE": "QUALITY_ISSUE",
    }.get(decision.decision.value, "QUALITY_ISSUE")


def _groups_from_pairs(pair_evidence: dict[tuple[str, str], PairEvidence]) -> list[AuditGroup]:
    groups: list[AuditGroup] = []
    by_relation: dict[str, list[PairEvidence]] = defaultdict(list)
    for evidence in pair_evidence.values():
        if evidence.relation != "PASS":
            by_relation[evidence.relation].append(evidence)
    for relation, pairs in by_relation.items():
        adjacency: dict[str, set[str]] = defaultdict(set)
        for pair in pairs:
            left, right = pair.pair
            adjacency[left].add(right)
            adjacency[right].add(left)
        visited: set[str] = set()
        evidence_by_pair = {item.pair: item for item in pairs}
        for start in sorted(adjacency):
            if start in visited:
                continue
            stack = [start]
            members: set[str] = set()
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                members.add(current)
                stack.extend(adjacency[current] - visited)
            member_ids = sorted(members)
            connected = [
                evidence_by_pair[pair]
                for pair in evidence_by_pair
                if set(pair).issubset(members)
            ]
            groups.append(
                AuditGroup(
                    group_id=_group_id(relation, member_ids),
                    relation=relation,
                    member_skill_ids=member_ids,
                    confidence=_group_confidence(connected),
                    same_points=_dedupe(item for evidence in connected for item in evidence.evidence),
                    recommendations=_dedupe(item for evidence in connected for item in evidence.recommendations),
                )
            )
    return groups


def _quality_groups(
    skills: list[SkillRecord],
    findings: dict[str, list[Finding]],
    existing: list[AuditGroup],
) -> list[AuditGroup]:
    covered = {member for group in existing for member in group.member_skill_ids}
    groups: list[AuditGroup] = []
    for skill in skills:
        related = findings.get(skill.skill_id, [])
        if not related or skill.skill_id in covered:
            continue
        groups.append(
            AuditGroup(
                group_id=_group_id("QUALITY_ISSUE", [skill.skill_id]),
                relation="QUALITY_ISSUE",
                member_skill_ids=[skill.skill_id],
                confidence="medium",
                same_points=[finding.message for finding in related],
                recommendations=[finding.remediation for finding in related],
            )
        )
    return groups


def _group_id(relation: str, member_ids: list[str]) -> str:
    digest = hashlib.sha256("|".join(member_ids).encode("utf-8")).hexdigest()[:10]
    return f"AG-{relation.lower()}-{digest}"


def _group_confidence(evidence: list[PairEvidence]) -> str:
    if any(item.confidence == "high" for item in evidence):
        return "high"
    return "medium" if evidence else "low"


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _relation_priority(relation: str) -> int:
    return {
        "QUALITY_ISSUE": 0,
        "EXACT_DUPLICATE": 1,
        "CONFLICT_GROUP": 2,
        "VARIANT_GROUP": 3,
        "HIGH_OVERLAP": 4,
    }.get(relation, 9)
