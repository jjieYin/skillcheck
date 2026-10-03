from __future__ import annotations

from math import sqrt

import pytest

from skillcheck.audit import LibraryAuditor
from skillcheck.core.features import PairSignals
from skillcheck.models.audit import PairEvidence
from tests.helpers import skill_record


def _triangle_vectors(ac: float) -> dict[str, list[float]]:
    ab = 0.91
    bc = 0.90
    by = sqrt(1 - ab * ab)
    cy = (bc - ab * ac) / by
    cz = sqrt(max(0.0, 1 - ac * ac - cy * cy))
    return {
        "a": [1.0, 0.0, 0.0],
        "b": [ab, by, 0.0],
        "c": [ac, cy, cz],
    }


def test_overlap_groups_do_not_follow_a_single_chain() -> None:
    skills = [
        skill_record(
            skill_id=item,
            name=f"name{item}",
            description=f"description{item}",
            content_hash=f"sha256:{item}",
            body=f"body{item}",
        )
        for item in "abc"
    ]
    result = LibraryAuditor(top_k=5).audit(skills, _triangle_vectors(0.70), findings=[])

    overlap_groups = [
        set(group.member_skill_ids)
        for group in result.groups
        if group.relation == "HIGH_OVERLAP_CANDIDATE"
    ]

    assert {"a", "b", "c"} not in overlap_groups
    assert {"a", "b"} in overlap_groups
    assert {"b", "c"} in overlap_groups


def test_fully_connected_overlap_group_records_similarity_statistics() -> None:
    skills = [
        skill_record(
            skill_id=item,
            name=f"name{item}",
            description=f"description{item}",
            content_hash=f"sha256:{item}",
            body=f"body{item}",
        )
        for item in "abc"
    ]
    result = LibraryAuditor(top_k=5).audit(skills, _triangle_vectors(0.88), findings=[])

    group = next(group for group in result.groups if group.relation == "HIGH_OVERLAP_CANDIDATE")
    values = [0.88, 0.90, 0.91]
    assert group.member_skill_ids == ["a", "b", "c"]
    assert group.min_similarity == pytest.approx(min(values), abs=1e-6)
    assert group.max_similarity == pytest.approx(max(values), abs=1e-6)
    assert group.mean_similarity == pytest.approx(sum(values) / 3, abs=1e-6)
    assert len(group.pair_evidence) == 3


def test_conflict_groups_are_always_binary() -> None:
    skills = [
        skill_record(skill_id="a", content_hash="sha256:a", permissions=["database-read"]),
        skill_record(skill_id="b", content_hash="sha256:b", permissions=["database-write", "database-read"]),
        skill_record(skill_id="c", content_hash="sha256:c", permissions=["database-write"]),
    ]
    vectors = {skill.skill_id: [1.0, 0.0] for skill in skills}

    result = LibraryAuditor(top_k=5).audit(skills, vectors, findings=[])

    conflicts = [group for group in result.groups if group.relation == "CONFLICT_CANDIDATE"]
    assert len(conflicts) == 3
    assert all(len(group.member_skill_ids) == 2 for group in conflicts)


def test_pair_evidence_model_exposes_stable_endpoints() -> None:
    evidence = PairEvidence(
        source_skill_id="a",
        target_skill_id="b",
        relation="HIGH_OVERLAP_CANDIDATE",
        signals=PairSignals(semantic_similarity=0.9),
        confidence="medium",
        evidence=["task overlap"],
    )

    assert evidence.pair == ("a", "b")
    assert evidence.similarity == 0.9
