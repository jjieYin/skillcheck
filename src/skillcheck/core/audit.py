from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from skillcheck.core.candidates import (
    ChannelThresholdProfile,
    HybridCandidateRetriever,
    MultiChannelCandidateRetriever,
)
from skillcheck.core.decisions import RuleDecision, RuleDecisionEngine
from skillcheck.models import AuditGroup, Finding, PairEvidence, Provider, Severity, SkillRecord

RELATION_MAP = {
    "SIMILAR": "HIGH_OVERLAP_CANDIDATE",
    "CONFLICT": "CONFLICT_CANDIDATE",
    "VARIANT": "VARIANT_CANDIDATE",
    "UNSAFE": "SECURITY_ISSUE",
}


@dataclass(frozen=True)
class AuditScope:
    provider: Provider | str | None = None
    root_path: Path | None = None


@dataclass
class AuditResult:
    groups: list[AuditGroup] = field(default_factory=list)
    compared_pairs: list[tuple[str, str]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    installation_count: int = 0
    unique_skill_count: int = 0
    pair_evidence: list[PairEvidence] = field(default_factory=list)


class LibraryAuditor:
    def __init__(self, top_k: int = 5, decision_engine: RuleDecisionEngine | None = None) -> None:
        self.top_k = max(1, top_k)
        self.decision_engine = decision_engine or RuleDecisionEngine()

    def audit(
        self,
        skills: Iterable[SkillRecord],
        vectors: Mapping[str, Iterable[float] | np.ndarray] | None,
        *,
        findings: list[Finding] | dict[str, list[Finding]],
        provider: Provider | str | None = None,
        root_path: Path | str | None = None,
        scope: AuditScope | None = None,
        source_skill_ids: set[str] | None = None,
        sections=None,
        channel_vectors=None,
        vectorizer_kind: str = "lexical_hash",
        vectorizer_descriptor: dict[str, object] | None = None,
        vectorizer_signature: str | None = None,
        threshold_profile: str | None = None,
        semantic_thresholds_calibrated: bool = False,
        vectorizer_degraded: str | None = None,
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
                    min_similarity=1.0,
                    mean_similarity=1.0,
                    max_similarity=1.0,
                )
            )

        available_vector_ids = set((vectors or {}).keys())
        if channel_vectors is not None:
            available_vector_ids.update(
                getattr(channel_vectors, "values", {}).keys()
            )
        for skill in selected:
            if skill.skill_id not in available_vector_ids:
                finding = Finding(
                    rule_id="AUDIT001",
                    severity=Severity.INFO,
                    message=f"Skill {skill.skill_id} has no embedding vector; semantic audit is degraded.",
                    evidence_path="SKILL.md",
                    remediation="Run skillcheck scan --refresh or configure an embedding backend.",
                )
                result.findings.append(finding)

        vector_rows = [
            np.asarray(vector, dtype=np.float32).reshape(-1)
            for skill_id, vector in (vectors or {}).items()
            if skill_id in by_id
        ]
        dimensions = {int(vector.size) for vector in vector_rows}
        if len(dimensions) > 1:
            result.findings.append(
                Finding(
                    rule_id="AUDIT002",
                    severity=Severity.INFO,
                    message=(
                        "Embedding vector dimensions are inconsistent: "
                        + ", ".join(str(value) for value in sorted(dimensions))
                    ),
                    evidence_path="catalog/vectors",
                    remediation="Reindex all active skills with one embedding configuration.",
                )
            )
        pair_evidence: dict[tuple[str, str], PairEvidence] = {}
        legacy_vector_compat = bool(
            channel_vectors is not None
            and getattr(getattr(channel_vectors, "descriptor", None), "backend", None)
            == "legacy"
        )
        if (sections is not None or channel_vectors is not None) and not legacy_vector_compat:
            candidates = MultiChannelCandidateRetriever(
                top_k=self.top_k,
                thresholds=ChannelThresholdProfile(
                    semantic_calibrated=semantic_thresholds_calibrated
                ),
            ).retrieve(
                selected,
                sections,
                channel_vectors,
                vectorizer_kind=vectorizer_kind,
            )
        else:
            candidates = HybridCandidateRetriever(top_k=self.top_k).retrieve(selected, vectors or {})
        for pair, signals in candidates.items():
            if source_skill_ids is not None and not (set(pair) & source_skill_ids):
                continue
            if signals.package_hash_equal:
                continue
            base, target = by_id[pair[0]], by_id[pair[1]]
            decision = self.decision_engine.decide(base, target, signals)
            pair_evidence[pair] = PairEvidence(
                source_skill_id=pair[0],
                target_skill_id=pair[1],
                relation="PASS" if decision.decision.value == "PASS" else _audit_relation(decision),
                confidence=decision.confidence,
                signals=signals,
                evidence=decision.evidence,
                recommendations=decision.recommendations,
                relation_score=_bounded_score(decision.relation_score),
                vectorizer_descriptor=vectorizer_descriptor,
                vectorizer_signature=vectorizer_signature,
                threshold_profile=threshold_profile,
                vectorizer_degraded=vectorizer_degraded,
            )

        if vectorizer_degraded:
            result.findings.append(
                Finding(
                    rule_id="AUDIT002",
                    severity=Severity.INFO,
                    message=f"Vectorizer degraded to lexical analysis: {vectorizer_degraded}",
                    evidence_path="catalog/segment_vectors",
                    remediation="Restore the configured vectorizer and re-run scan to refresh dense evidence.",
                )
            )

        result.compared_pairs = sorted(pair_evidence)
        result.pair_evidence = sorted(pair_evidence.values(), key=lambda item: item.pair)
        result.groups.extend(_groups_from_pairs(pair_evidence))
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


def _global_findings(findings: list[Finding] | dict[str, list[Finding]]) -> list[Finding]:
    return findings if isinstance(findings, list) else [item for values in findings.values() for item in values]


def _bounded_score(value: float | None) -> float | None:
    if value is None:
        return None
    return min(1.0, max(0.0, float(value)))


def _audit_relation(decision: RuleDecision) -> str:
    if decision.relation and decision.relation != "PASS":
        return decision.relation
    return RELATION_MAP.get(decision.decision.value, "QUALITY_ISSUE")


def _groups_from_pairs(pair_evidence: dict[tuple[str, str], PairEvidence]) -> list[AuditGroup]:
    groups: list[AuditGroup] = []
    by_relation: dict[str, list[PairEvidence]] = defaultdict(list)
    for evidence in pair_evidence.values():
        if evidence.relation != "PASS":
            by_relation[evidence.relation].append(evidence)
    for relation, pairs in by_relation.items():
        if relation in {"CONFLICT_CANDIDATE", "CONSTRAINT_MISMATCH_CANDIDATE"}:
            member_sets = [
                ({item.source_skill_id, item.target_skill_id}, [item]) for item in pairs
            ]
        else:
            member_sets = _fully_connected_sets(pairs)
        for members, connected in member_sets:
            member_ids = sorted(members)
            similarities = [item.similarity for item in connected]
            groups.append(
                AuditGroup(
                    group_id=_group_id(relation, member_ids),
                    relation=relation,
                    member_skill_ids=member_ids,
                    confidence=_group_confidence(connected),
                    same_points=_dedupe(item for evidence in connected for item in evidence.evidence),
                    recommendations=_dedupe(item for evidence in connected for item in evidence.recommendations),
                    pair_evidence=sorted(connected, key=lambda item: item.pair),
                    min_similarity=min(similarities) if similarities else None,
                    mean_similarity=sum(similarities) / len(similarities) if similarities else None,
                    max_similarity=max(similarities) if similarities else None,
                )
            )
    return groups


def _fully_connected_sets(
    pairs: list[PairEvidence],
) -> list[tuple[set[str], list[PairEvidence]]]:
    """Merge only groups whose union has every same-relation cross edge."""

    edge_by_pair = {item.pair: item for item in pairs}
    groups: list[set[str]] = [{item.source_skill_id, item.target_skill_id} for item in pairs]
    changed = True
    while changed:
        changed = False
        for left_index in range(len(groups)):
            for right_index in range(left_index + 1, len(groups)):
                union = groups[left_index] | groups[right_index]
                if len(union) <= max(len(groups[left_index]), len(groups[right_index])):
                    continue
                if all(
                    tuple(sorted((left, right))) in edge_by_pair
                    for index, left in enumerate(sorted(union))
                    for right in sorted(union)[index + 1 :]
                ):
                    groups[left_index] = union
                    groups.pop(right_index)
                    changed = True
                    break
            if changed:
                break
    # A complete larger clique subsumes its edge-sized intermediate groups.
    groups = [
        group
        for group in groups
        if not any(group < other for other in groups)
    ]
    result: list[tuple[set[str], list[PairEvidence]]] = []
    for group in sorted(groups, key=lambda item: (len(item), sorted(item))):
        connected = [
            edge_by_pair[pair]
            for index, left in enumerate(sorted(group))
            for right in sorted(group)[index + 1 :]
            if (pair := tuple(sorted((left, right)))) in edge_by_pair
        ]
        result.append((group, connected))
    return result


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
        relation = "SECURITY_ISSUE" if any(_is_security_finding(item) for item in related) else "QUALITY_ISSUE"
        groups.append(
            AuditGroup(
                group_id=_group_id(relation, [skill.skill_id]),
                relation=relation,
                member_skill_ids=[skill.skill_id],
                confidence="medium",
                same_points=[finding.message for finding in related],
                recommendations=[finding.remediation for finding in related],
            )
        )
    return groups


def _is_security_finding(finding: Finding) -> bool:
    if finding.rule_id.upper().startswith("SEC"):
        return True
    if finding.severity not in {Severity.HIGH, Severity.CRITICAL}:
        return False
    text = f"{finding.message} {finding.remediation}".casefold()
    return any(term in text for term in ("credential", "secret", "token", "api key", "password"))


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
        "EXACT_DUPLICATE": 0,
        "CONFLICT_CANDIDATE": 1,
        "VARIANT_CANDIDATE": 2,
        "HIGH_OVERLAP_CANDIDATE": 3,
        "SECURITY_ISSUE": 4,
        "QUALITY_ISSUE": 5,
    }.get(relation, 9)
