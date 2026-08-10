from __future__ import annotations

from dataclasses import dataclass, field

from skillcheck.config import ThresholdConfig
from skillcheck.models import CandidateMatch, Decision, Finding, Severity, SkillRecord


@dataclass(frozen=True)
class RuleDecision:
    decision: Decision
    confidence: str
    blocking: bool
    evidence: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


class RuleDecisionEngine:
    """Conservative, explainable relationship classifier for two Skills."""

    def __init__(self, thresholds: ThresholdConfig | None = None) -> None:
        self.thresholds = thresholds or ThresholdConfig()

    def decide(
        self,
        base: SkillRecord,
        candidate: CandidateMatch,
        findings: list[Finding],
    ) -> RuleDecision:
        target = candidate.skill
        evidence: list[str] = [f"cosine similarity={candidate.similarity:.3f}"]
        high_findings = [
            finding
            for finding in findings
            if finding.severity in {Severity.HIGH, Severity.CRITICAL}
        ]
        if high_findings:
            evidence.extend(f"{finding.rule_id}: {finding.message}" for finding in high_findings)
            return RuleDecision(
                Decision.UNSAFE,
                "high",
                True,
                evidence,
                [finding.remediation for finding in high_findings],
            )
        if (
            base.content_hash == target.content_hash
            and candidate.similarity >= self.thresholds.duplicate_similarity
        ):
            return RuleDecision(
                Decision.DUPLICATE,
                "high",
                True,
                evidence + ["content hashes are identical"],
                ["保留一个权威副本，删除或停用重复 Skill。"],
            )
        if self._permissions_conflict(base, target):
            evidence.append("permission scopes contain opposing read/write operations")
            return RuleDecision(
                Decision.CONFLICT,
                "high",
                True,
                evidence,
                ["拆分权限边界，明确只读/写入场景，并要求人工复核。"],
            )
        if self._environment_variant(base, target) and candidate.similarity >= self.thresholds.variant_similarity:
            evidence.append("environment constraints differ")
            return RuleDecision(
                Decision.VARIANT,
                "medium",
                False,
                evidence,
                ["保留为显式环境变体，并在名称和触发条件中标注环境。"],
            )
        if candidate.similarity >= self.thresholds.overlap_similarity:
            evidence.append("task and implementation signals overlap")
            return RuleDecision(
                Decision.SIMILAR,
                "medium",
                False,
                evidence,
                ["对比完整步骤，必要时合并能力或补充边界说明。"],
            )
        return RuleDecision(
            Decision.PASS,
            "low",
            False,
            evidence,
            ["当前没有足够证据判定重复或冲突。"],
        )

    @staticmethod
    def _environment_variant(base: SkillRecord, candidate: SkillRecord) -> bool:
        left = {value.casefold() for value in base.environments}
        right = {value.casefold() for value in candidate.environments}
        return bool(left and right and left.isdisjoint(right))

    @staticmethod
    def _permissions_conflict(base: SkillRecord, candidate: SkillRecord) -> bool:
        left = _permission_modes(base.permissions)
        right = _permission_modes(candidate.permissions)
        for resource in left.keys() & right.keys():
            if left[resource] != right[resource] and {left[resource], right[resource]} >= {"read", "write"}:
                return True
        return False


def _permission_modes(permissions: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for permission in permissions:
        normalized = permission.casefold().strip()
        if normalized.endswith("-read"):
            result[normalized[:-5]] = "read"
        elif normalized.endswith("-write"):
            result[normalized[:-6]] = "write"
    return result
