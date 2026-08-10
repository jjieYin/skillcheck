import pytest

from skillcheck.reviewers.validation import validate_agent_output


def test_unknown_agent_decision_is_rejected() -> None:
    with pytest.raises(ValueError, match="decision"):
        validate_agent_output(
            '{"groups":[{"group_id":"g1","decision":"EXECUTE_COMMAND","confidence":1,"reason":"x"}]}'
        )


def test_valid_agent_output_is_converted() -> None:
    result = validate_agent_output(
        '{"groups":[{"group_id":"g1","decision":"MERGE","confidence":0.8,"reason":"same boundary"}]}'
    )
    assert result.groups[0].decision == "MERGE"

