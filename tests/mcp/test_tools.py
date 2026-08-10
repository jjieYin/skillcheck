from __future__ import annotations

from types import SimpleNamespace

from skillcheck.mcp.tools import SkillcheckQueries


def test_group_query_returns_evidence_without_full_body() -> None:
    repositories = SimpleNamespace(
        reports=SimpleNamespace(latest_summary=lambda: {"skill_count": 2}),
        groups=SimpleNamespace(
            list_public=lambda **kwargs: [
                {
                    "group_id": "overlap-001",
                    "evidence": ["same trigger"],
                    "body": "must not be exposed",
                }
            ]
        ),
    )
    result = SkillcheckQueries(repositories).groups(limit=10)
    assert result[0]["group_id"] == "overlap-001"
    assert result[0]["evidence"]
    assert "body" not in result[0]


def test_queries_bound_limit_and_redact_sensitive_fields() -> None:
    repositories = SimpleNamespace(
        reports=SimpleNamespace(
            latest_summary=lambda: {"api_key": "secret", "report_id": "r1"},
            get_public=lambda report_id: {"report_id": report_id, "content": "hidden"},
        ),
        groups=SimpleNamespace(list_public=lambda **kwargs: []),
    )
    queries = SkillcheckQueries(repositories)
    assert "api_key" not in queries.summary()
    assert "content" not in queries.report("r1")
    assert queries.groups(limit=0) == []

