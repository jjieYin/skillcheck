from __future__ import annotations

from skillcheck.models.review import AgentReview, ReviewStatus
from skillcheck.reports.builder import ReportDocument
from skillcheck.reports.markdown import render_markdown


def test_markdown_keeps_three_evidence_layers() -> None:
    document = ReportDocument(
        report_id="r1",
        run_id="run1",
        skill_count=2,
        installation_count=2,
        unique_skill_count=2,
        groups=[{"group_id": "g1", "relation": "HIGH_OVERLAP", "member_skill_ids": ["a", "b"]}],
        findings=[{"rule_id": "R1", "message": "finding"}],
        agent_review=AgentReview(
            review_id="review1",
            run_id="run1",
            agent="codex",
            status=ReviewStatus.FAILED,
            schema_version="1",
            full_text_shared=False,
            error="Codex 复核未完成",
        ),
    )
    markdown = render_markdown(document)
    assert "## 确定性检查结论" in markdown
    assert "## 本地相似度分析" in markdown
    assert "## Agent 语义复核" in markdown

