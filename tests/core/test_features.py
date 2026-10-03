from __future__ import annotations

from skillcheck.core.features import (
    PairSignals,
    PairSignalsV2,
    activation_text,
    idf_weights,
    lexical_features,
    procedure_text,
    weighted_counter_cosine,
)
from tests.helpers import skill_record


def test_pair_signals_keep_relation_evidence_independent_from_findings() -> None:
    signals = PairSignals(
        semantic_similarity=0.91,
        dense_similarity=0.91,
        lexical_similarity=0.80,
        capability_similarity=0.75,
        permission_conflict=False,
        environment_variant=True,
        package_hash_equal=False,
        instruction_hash_equal=True,
    )

    assert signals.semantic_similarity == 0.91
    assert signals.instruction_hash_equal is True
    assert signals.permission_conflict is False


def test_lexical_features_are_unicode_aware_and_ignore_markdown_noise() -> None:
    first = lexical_features("## 中文接口\nCheck API fields")
    second = lexical_features("中文接口 Check   API fields")

    assert first == second
    assert any(len(token) in {2, 3, 4} for token in first if any("\u4e00" <= c <= "\u9fff" for c in token))
    assert "check" in first
    assert "check api" in first
    assert "##" not in first


def test_embedding_text_helpers_do_not_add_fixed_field_labels() -> None:
    skill = skill_record(
        name="API helper",
        description="Check requests",
        body="Validate response fields.",
        allowed_tools=["http-client"],
    )

    assert "name:" not in activation_text(skill)
    assert "description:" not in activation_text(skill)
    assert "body:" not in procedure_text(skill)
    assert "http-client" in activation_text(skill)


def test_pair_signals_alias_exposes_v2_channels_without_breaking_legacy_fields() -> None:
    signals = PairSignalsV2(
        package_hash_equal=False,
        behavior_hash_equal=True,
        execution_equivalent=False,
        activation_lexical_similarity=0.9,
        procedure_coverage_left=1.0,
        procedure_coverage_right=0.5,
        constraint_polarity_mismatch=True,
    )

    assert isinstance(signals, PairSignals)
    assert signals.behavior_hash_equal is True
    assert signals.constraint_polarity_mismatch is True


def test_idf_downweights_repeated_template_features_and_caps_frequency() -> None:
    documents = [
        lexical_features("follow the instructions and report the result database index"),
        lexical_features("follow the instructions and report the result image dimension"),
    ]

    weights = idf_weights(documents)

    assert weights["database"] > weights["follow"]
    assert weighted_counter_cosine(
        lexical_features("follow follow follow database"),
        lexical_features("follow instructions database"),
        weights,
    ) < 1.0
