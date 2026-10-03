from __future__ import annotations

from dataclasses import dataclass, field

from skillcheck.config import ThresholdConfig
from skillcheck.core.features import PairSignals
from skillcheck.models import CandidateMatch, Decision, Finding, Severity, SkillRecord

_V2_ACTIVATION_GATE = 0.50
_V2_STRONG_PROCEDURE_FLOOR = 0.45
_V2_HIGH_COVERAGE = 0.66
_V2_LOW_COVERAGE = 0.34


@dataclass(frozen=True)
class RuleDecision:
    decision: Decision
    confidence: str
    blocking: bool
    evidence: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    relation: str = "PASS"
    relation_score: float | None = None


class RuleDecisionEngine:
    """Conservative, explainable relationship classifier for two Skills."""

    def __init__(self, thresholds: ThresholdConfig | None = None) -> None:
        self.thresholds = thresholds or ThresholdConfig()

    def decide(
        self,
        base: SkillRecord,
        target: SkillRecord | CandidateMatch,
        signals: PairSignals | list[Finding] | None = None,
    ) -> RuleDecision:
        legacy_candidate = target if isinstance(target, CandidateMatch) else None
        target_skill = legacy_candidate.skill if legacy_candidate is not None else target
        if legacy_candidate is not None:
            legacy_findings = signals if isinstance(signals, list) else []
            high_findings = [
                finding
                for finding in legacy_findings
                if finding.severity in {Severity.HIGH, Severity.CRITICAL}
            ]
            if high_findings:
                evidence = [f"cosine similarity={legacy_candidate.similarity:.3f}"]
                evidence.extend(f"{finding.rule_id}: {finding.message}" for finding in high_findings)
                return RuleDecision(
                    Decision.UNSAFE,
                    "high",
                    True,
                    evidence,
                    [finding.remediation for finding in high_findings],
                    relation="SECURITY_ISSUE",
                    relation_score=legacy_candidate.similarity,
                )
            pair_signals = PairSignals(
                semantic_similarity=legacy_candidate.similarity,
                permission_conflict=self._permissions_conflict(base, target_skill),
                environment_variant=self._environment_variant(base, target_skill),
                package_hash_equal=base.content_hash == target_skill.content_hash,
            )
        elif isinstance(signals, PairSignals):
            pair_signals = signals
        else:
            raise TypeError("pair decisions require PairSignals")

        if _has_v2_channels(pair_signals):
            return self._decide_v2(base, target_skill, pair_signals)
        return self._decide_legacy(base, target_skill, pair_signals)

    def _decide_legacy(
        self, base: SkillRecord, target: SkillRecord, signals: PairSignals
    ) -> RuleDecision:
        similarity = signals.semantic_similarity or 0.0
        evidence: list[str] = [f"semantic similarity={similarity:.3f}"]
        if signals.instruction_hash_equal and not signals.package_hash_equal:
            evidence.append("instructions identical; package assets differ")
        if signals.package_hash_equal and similarity >= self.thresholds.duplicate_similarity:
            return RuleDecision(
                Decision.DUPLICATE,
                "high",
                True,
                evidence + ["content hashes are identical"],
                ["保留一个权威副本，删除或停用重复 Skill。"],
                relation="EXACT_DUPLICATE",
                relation_score=1.0,
            )
        if signals.permission_conflict and similarity >= self.thresholds.conflict_similarity:
            evidence.append("permission scopes contain opposing read/write operations")
            return RuleDecision(
                Decision.CONFLICT,
                "high",
                True,
                evidence,
                ["拆分权限边界，明确只读/写入场景，并要求人工复核。"],
                relation="CONFLICT_CANDIDATE",
                relation_score=similarity,
            )
        if signals.environment_variant and similarity >= self.thresholds.variant_similarity:
            evidence.append("environment constraints differ")
            return RuleDecision(
                Decision.VARIANT,
                "medium",
                False,
                evidence,
                ["保留为显式环境变体，并在名称和触发条件中标注环境。"],
                relation="VARIANT_CANDIDATE",
                relation_score=similarity,
            )
        if similarity >= self.thresholds.overlap_similarity:
            evidence.append("task and implementation signals overlap")
            return RuleDecision(
                Decision.SIMILAR,
                "medium",
                False,
                evidence,
                ["对比完整步骤，必要时合并能力或补充边界说明。"],
                relation="HIGH_OVERLAP_CANDIDATE",
                relation_score=similarity,
            )
        return RuleDecision(
            Decision.PASS,
            "low",
            False,
            evidence,
            ["当前没有足够证据判定重复或冲突。"],
            relation="PASS",
            relation_score=similarity,
        )

    def _decide_v2(
        self, base: SkillRecord, target: SkillRecord, signals: PairSignals
    ) -> RuleDecision:
        activation = signals.activation_lexical_similarity
        dense_activation = signals.activation_dense_similarity
        if signals.package_hash_equal:
            return RuleDecision(
                Decision.DUPLICATE,
                "high",
                True,
                ["package hashes are identical"],
                ["保留一个权威副本，删除或停用重复 Skill。"],
                relation="EXACT_DUPLICATE",
                relation_score=1.0,
            )

        if signals.behavior_hash_equal and signals.execution_equivalent:
            return RuleDecision(
                Decision.DUPLICATE,
                "high",
                True,
                ["behavior hashes are identical and executable content is equivalent"],
                ["保留一个行为权威副本，审查仅有资源或格式差异的副本。"],
                relation="BEHAVIOR_DUPLICATE_CANDIDATE",
                relation_score=1.0,
            )

        if signals.behavior_hash_equal and not signals.execution_equivalent:
            return RuleDecision(
                Decision.VARIANT,
                "medium",
                False,
                ["behavior hashes match but executable content differs"],
                ["保留实现变体，并明确脚本差异及运行边界。"],
                relation="IMPLEMENTATION_VARIANT_CANDIDATE",
                relation_score=1.0,
            )

        dense_used = dense_activation is not None or signals.semantic_similarity is not None
        calibrated_dense = dense_used and signals.semantic_model_calibrated
        activation_score = dense_activation if calibrated_dense and dense_activation is not None else activation
        left = (
            signals.procedure_dense_coverage_left
            if calibrated_dense and signals.procedure_dense_coverage_left is not None
            else signals.procedure_coverage_left
        )
        right = (
            signals.procedure_dense_coverage_right
            if calibrated_dense and signals.procedure_dense_coverage_right is not None
            else signals.procedure_coverage_right
        )
        lexical_score = activation_score or signals.hashed_lexical_similarity or signals.constraint_action_similarity

        # A semantic model without a calibrated profile is retrieval-only. It
        # may add a candidate, but it cannot override an existing lexical
        # relation or manufacture one from a dense score alone.
        if dense_used and not signals.semantic_model_calibrated and not (
            lexical_score is not None and lexical_score > 0
        ):
            return RuleDecision(
                Decision.MANUAL_REVIEW,
                "low",
                False,
                ["semantic vector candidate is not attached to a calibrated threshold profile"],
                ["先完成标注集校准，再允许语义分数驱动自动关系。"],
                relation="MANUAL_REVIEW",
                relation_score=signals.semantic_similarity,
            )

        score = lexical_score or (signals.semantic_similarity if calibrated_dense else None)

        # Permission and environment differences are safety boundaries and
        # must not be swallowed by a high procedural overlap relation.
        if signals.permission_conflict and score is not None and score >= self.thresholds.conflict_similarity:
            return RuleDecision(
                Decision.CONFLICT,
                "high",
                True,
                ["permission scopes contain opposing read/write operations"],
                ["拆分权限边界并要求人工复核。"],
                relation="CONFLICT_CANDIDATE",
                relation_score=score,
            )
        if signals.environment_variant and score is not None and score >= self.thresholds.variant_similarity:
            return RuleDecision(
                Decision.VARIANT,
                "medium",
                False,
                ["environment constraints differ"],
                ["保留为显式环境变体，并标注环境边界。"],
                relation="VARIANT_CANDIDATE",
                relation_score=score,
            )

        if (
            signals.constraint_polarity_mismatch
            and signals.constraint_action_similarity is not None
            and signals.constraint_action_similarity >= _V2_ACTIVATION_GATE
        ):
            return RuleDecision(
                Decision.MANUAL_REVIEW,
                "medium",
                False,
                ["matching constraint action has different polarity"],
                ["人工确认 required/forbidden 约束是否代表真实冲突。"],
                relation="CONSTRAINT_MISMATCH_CANDIDATE",
                relation_score=signals.constraint_action_similarity,
            )

        if (
            activation_score is not None
            and (
                activation_score >= _V2_ACTIVATION_GATE
                or (
                    activation_score >= _V2_STRONG_PROCEDURE_FLOOR
                    and left is not None
                    and right is not None
                    and left >= _V2_HIGH_COVERAGE
                    and right >= _V2_HIGH_COVERAGE
                    and (signals.hashed_lexical_similarity or 0.0) >= 0.85
                )
            )
            and left is not None
            and right is not None
            and left >= _V2_HIGH_COVERAGE
            and right >= _V2_HIGH_COVERAGE
            and not signals.constraint_polarity_mismatch
        ):
            score = min(activation_score, left, right)
            return RuleDecision(
                Decision.SIMILAR,
                "medium",
                False,
                [
                    f"activation similarity={activation_score:.3f}",
                    f"procedure coverage left/right={left:.3f}/{right:.3f}",
                ],
                ["对比完整步骤，必要时合并能力或补充边界说明。"],
                relation="HIGH_OVERLAP_CANDIDATE",
                relation_score=score,
            )

        if (
            activation_score is not None
            and activation_score >= _V2_ACTIVATION_GATE
            and left is not None
            and right is not None
            and max(left, right) >= _V2_HIGH_COVERAGE
            and min(left, right) < _V2_HIGH_COVERAGE
            and max(left, right) - min(left, right) >= 0.25
        ):
            direction = "right contains left" if left > right else "left contains right"
            score = min(activation_score, max(left, right))
            return RuleDecision(
                Decision.SIMILAR,
                "medium",
                False,
                [f"procedure coverage direction: {direction}"],
                ["保留包含关系，并检查较窄 Skill 是否应作为独立边界。"],
                relation="CONTAINMENT_CANDIDATE",
                relation_score=score,
            )

        if score is not None and score >= _V2_ACTIVATION_GATE:
            return RuleDecision(
                Decision.MANUAL_REVIEW,
                "low",
                False,
                ["candidate evidence is below a relation-specific gate"],
                ["保留分通道证据，交由人工确认。"],
                relation="MANUAL_REVIEW",
                relation_score=score,
            )
        return RuleDecision(
            Decision.PASS,
            "low",
            False,
            ["当前没有足够证据判定关系。"],
            ["继续保持独立 Skill。"],
            relation="PASS",
            relation_score=0.0,
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
            left_modes = left[resource]
            right_modes = right[resource]
            if ("read" in left_modes and "write" in right_modes) or (
                "write" in left_modes and "read" in right_modes
            ):
                return True
        return False


def _has_v2_channels(signals: PairSignals) -> bool:
    return signals.signals_version == "v2" and any(
        value is not None
        for value in (
            signals.activation_lexical_similarity,
            signals.procedure_coverage_left,
            signals.procedure_coverage_right,
            signals.constraint_action_similarity,
            signals.activation_dense_similarity,
            signals.procedure_dense_coverage_left,
            signals.procedure_dense_coverage_right,
        )
    ) or any(
        (
            signals.behavior_hash_equal,
            signals.execution_present_left,
            signals.execution_present_right,
            signals.constraint_polarity_mismatch,
        )
    )


def _permission_modes(permissions: list[str]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for permission in permissions:
        normalized = permission.casefold().strip()
        if normalized.endswith("-read"):
            result.setdefault(normalized[:-5], set()).add("read")
        elif normalized.endswith("-write"):
            result.setdefault(normalized[:-6], set()).add("write")
    return result
