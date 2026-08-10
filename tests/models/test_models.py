from datetime import UTC, datetime

from skillcheck.models.audit import Evidence, GovernanceGroup, Relation
from skillcheck.models.review import AgentDecision, AgentReview, ReviewStatus


def test_review_and_group_round_trip() -> None:
    group = GovernanceGroup(
        group_id="overlap-001",
        relation=Relation.HIGH_OVERLAP,
        member_skill_ids=["a", "b"],
        similarity=0.91,
        evidence=[
            Evidence(
                kind="similarity",
                source_skill_id="a",
                target_skill_id="b",
                value="0.91",
            )
        ],
        rule_suggestion="REWRITE_BOUNDARY",
        requires_semantic_review=True,
    )
    review = AgentReview(
        review_id="review-001",
        run_id="run-001",
        agent="codex",
        status=ReviewStatus.COMPLETED,
        schema_version="1",
        full_text_shared=False,
        decisions=[
            AgentDecision(
                group_id=group.group_id,
                decision="MERGE",
                confidence=0.86,
                reason="边界重叠",
            )
        ],
    )
    restored = AgentReview.model_validate_json(review.model_dump_json())
    assert restored.decisions[0].group_id == "overlap-001"
    assert restored.decisions[0].confidence == 0.86
    assert datetime.now(UTC).tzinfo is not None
