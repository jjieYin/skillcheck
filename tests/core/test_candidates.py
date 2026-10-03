from __future__ import annotations

from pathlib import Path

import numpy as np

from skillcheck.core.candidates import HybridCandidateRetriever
from skillcheck.models import SkillRecord


def _skill(skill_id: str, *, body: str, instruction_hash: str = "") -> SkillRecord:
    return SkillRecord(
        skill_id=skill_id,
        name=skill_id,
        description="",
        root_path=Path("/skills") / skill_id,
        body=body,
        content_hash=f"package:{skill_id}",
        instruction_hash=instruction_hash,
    )


def test_instruction_hash_pair_is_recalled_even_outside_other_top_k() -> None:
    skills = [
        _skill("a", body="alpha procedure", instruction_hash="same-instructions"),
        _skill("b", body="unrelated words", instruction_hash="same-instructions"),
        _skill("c", body="alpha procedure"),
    ]
    pairs = HybridCandidateRetriever(top_k=1).retrieve(
        skills,
        {"a": np.array([1.0, 0.0]), "b": np.array([0.0, 1.0]), "c": np.array([1.0, 0.0])},
    )

    assert ("a", "b") in pairs
    assert pairs[("a", "b")].instruction_hash_equal is True


def test_lexical_channel_recalls_cjk_without_dense_vectors() -> None:
    skills = [
        _skill("a", body="检查接口返回字段并报告错误"),
        _skill("b", body="检查接口返回字段并记录错误"),
        _skill("c", body="完全无关的天气信息"),
    ]

    pairs = HybridCandidateRetriever(top_k=1).retrieve(skills, {})

    assert ("a", "b") in pairs
    assert pairs[("a", "b")].lexical_similarity is not None
    assert pairs[("a", "b")].semantic_similarity > 0


def test_dense_channel_can_recall_low_lexical_overlap() -> None:
    skills = [_skill("a", body="alpha"), _skill("b", body="omega"), _skill("c", body="noise")]
    pairs = HybridCandidateRetriever(top_k=1).retrieve(
        skills,
        {"a": np.array([1.0, 0.0]), "b": np.array([0.99, 0.01]), "c": np.array([0.0, 1.0])},
    )

    assert ("a", "b") in pairs
    assert pairs[("a", "b")].dense_similarity is not None


def test_capability_similarity_is_field_qualified() -> None:
    first = _skill("a", body="body")
    second = _skill("b", body="body")
    first.allowed_tools = ["read"]
    first.tools = ["shared"]
    second.allowed_tools = ["shared"]
    second.tools = ["read"]

    pairs = HybridCandidateRetriever(top_k=1).retrieve([first, second], {})

    assert pairs[("a", "b")].capability_similarity == 0.0
