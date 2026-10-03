from __future__ import annotations

from pathlib import Path

import numpy as np

from skillcheck.core.candidates import ChannelThresholdProfile, MultiChannelCandidateRetriever
from skillcheck.core.decisions import RuleDecisionEngine
from skillcheck.core.features import PairSignals
from skillcheck.core.fingerprints import EMPTY_EXECUTION_HASH
from skillcheck.core.sections import extract_skill_sections
from skillcheck.embeddings import VectorizerDescriptor
from skillcheck.models import Decision, SkillRecord
from skillcheck.vectorization import ChannelVectors


def _skill(skill_id: str, body: str, **fields) -> SkillRecord:
    return SkillRecord(
        skill_id=skill_id,
        name=skill_id,
        description=fields.pop("description", "validate an API request"),
        root_path=Path("/skills") / skill_id,
        body=body,
        content_hash=fields.pop("content_hash", f"package:{skill_id}"),
        **fields,
    )


def test_behavior_and_execution_hash_channels_are_unlimited() -> None:
    skills = [
        _skill("a", "alpha", behavior_hash="same", execution_hash="exec-a"),
        _skill("b", "unrelated", behavior_hash="same", execution_hash="exec-b"),
        _skill("c", "noise", behavior_hash="other", execution_hash="exec-c"),
    ]
    pairs = MultiChannelCandidateRetriever(top_k=1).retrieve(skills)

    assert ("a", "b") in pairs
    assert pairs[("a", "b")].behavior_hash_equal is True
    assert pairs[("a", "b")].execution_equivalent is False


def test_polarity_is_preserved_as_constraint_evidence() -> None:
    required = _skill("required", "The tool must write the report.")
    forbidden = _skill("forbidden", "The tool must not write the report.")
    pairs = MultiChannelCandidateRetriever(top_k=2).retrieve([required, forbidden])

    assert ("forbidden", "required") in pairs
    assert pairs[("forbidden", "required")].constraint_polarity_mismatch is True


def test_uncalibrated_semantic_candidates_are_retrieval_only() -> None:
    skills = [_skill("a", "alpha"), _skill("b", "omega")]
    descriptor = VectorizerDescriptor(
        backend="sentence-transformers",
        model_id="local-test",
        revision="1",
        dimensions=2,
        kind="semantic",
        locality="local",
        normalized=True,
    )
    vectors = ChannelVectors(
        descriptor=descriptor,
        values={
            "a": {"activation": (np.array([1.0, 0.0], dtype=np.float32),)},
            "b": {"activation": (np.array([0.99, 0.01], dtype=np.float32),)},
        },
    )
    signals = MultiChannelCandidateRetriever(top_k=1).retrieve(
        skills,
        {skill.skill_id: extract_skill_sections(skill) for skill in skills},
        vectors,
        vectorizer_kind="semantic",
    )[("a", "b")]

    assert signals.semantic_similarity is not None
    assert signals.semantic_model_calibrated is False
    decision = RuleDecisionEngine().decide(skills[0], skills[1], signals)
    assert decision.decision is Decision.MANUAL_REVIEW
    assert decision.relation == "MANUAL_REVIEW"


def test_calibrated_semantic_candidates_do_not_fill_lexical_field() -> None:
    skills = [_skill("a", "alpha"), _skill("b", "omega")]
    descriptor = VectorizerDescriptor(
        backend="sentence-transformers",
        model_id="local-test",
        revision="1",
        dimensions=2,
        kind="semantic",
        locality="local",
        normalized=True,
    )
    vectors = ChannelVectors(
        descriptor=descriptor,
        values={
            "a": {"activation": (np.array([1.0, 0.0], dtype=np.float32),)},
            "b": {"activation": (np.array([0.99, 0.01], dtype=np.float32),)},
        },
    )
    signals = MultiChannelCandidateRetriever(
        top_k=1,
        thresholds=ChannelThresholdProfile(semantic_calibrated=True),
    ).retrieve(
        skills,
        {skill.skill_id: extract_skill_sections(skill) for skill in skills},
        vectors,
        vectorizer_kind="semantic",
    )[("a", "b")]
    assert signals.semantic_similarity is not None
    assert signals.hashed_lexical_similarity is not None
    assert signals.semantic_similarity != signals.hashed_lexical_similarity


def test_empty_or_unknown_execution_hashes_do_not_create_execution_duplicates() -> None:
    empty_left = _skill(
        "empty-left",
        "unrelated weather procedure",
        description="summarize weather forecasts",
        behavior_hash="behavior-left",
        execution_hash=EMPTY_EXECUTION_HASH,
    )
    empty_right = _skill(
        "empty-right",
        "compress project archives",
        description="compress project archives",
        behavior_hash="behavior-right",
        execution_hash=EMPTY_EXECUTION_HASH,
    )
    assert not MultiChannelCandidateRetriever().retrieve([empty_left, empty_right])

    unknown_left = _skill("unknown-left", "same procedure", behavior_hash="same", execution_hash=None)
    unknown_right = _skill("unknown-right", "same procedure", behavior_hash="same", execution_hash=None)
    signals = MultiChannelCandidateRetriever().retrieve([unknown_left, unknown_right])[("unknown-left", "unknown-right")]
    assert signals.execution_equivalent is False
    assert RuleDecisionEngine().decide(unknown_left, unknown_right, signals).relation == (
        "IMPLEMENTATION_VARIANT_CANDIDATE"
    )


def test_uncalibrated_dense_evidence_does_not_override_lexical_relation() -> None:
    left = _skill("left", "validate and report API requests")
    right = _skill("right", "validate and report API requests")
    signals = PairSignals(
        semantic_similarity=0.99,
        activation_lexical_similarity=0.80,
        procedure_coverage_left=1.0,
        procedure_coverage_right=1.0,
        hashed_lexical_similarity=1.0,
        semantic_model_calibrated=False,
    )
    assert RuleDecisionEngine().decide(left, right, signals).relation == "HIGH_OVERLAP_CANDIDATE"


def test_relation_gates_preserve_direction_and_permission_boundaries() -> None:
    left = _skill("left", "validate API requests", permissions=["database-read"])
    right = _skill("right", "validate API requests", permissions=["database-write"])
    conflict = PairSignals(
        activation_lexical_similarity=0.90,
        procedure_coverage_left=1.0,
        procedure_coverage_right=1.0,
        hashed_lexical_similarity=0.90,
        permission_conflict=True,
    )
    assert RuleDecisionEngine().decide(left, right, conflict).relation == "CONFLICT_CANDIDATE"

    containment = PairSignals(
        activation_lexical_similarity=0.80,
        procedure_coverage_left=1.0,
        procedure_coverage_right=0.25,
        hashed_lexical_similarity=0.80,
    )
    decision = RuleDecisionEngine().decide(left, right, containment)
    assert decision.relation == "CONTAINMENT_CANDIDATE"
    assert decision.evidence == ["procedure coverage direction: right contains left"]
