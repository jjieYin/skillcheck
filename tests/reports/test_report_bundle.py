import json
from datetime import UTC, datetime

from skillcheck.models.audit import GovernanceGroup, Relation
from skillcheck.models.report import ScanRun
from skillcheck.models.review import AgentReview, ReviewStatus
from skillcheck.reports.builder import ReportBuilder


class Inventory:
    installation_count = 2
    unique_skills = [object(), object()]


class Analysis:
    groups = [
        GovernanceGroup(
            group_id="overlap-001",
            relation=Relation.HIGH_OVERLAP,
            member_skill_ids=["a", "b"],
            similarity=0.9,
            rule_suggestion="REWRITE_BOUNDARY",
            requires_semantic_review=True,
        )
    ]
    findings = []
    capabilities = ["hash"]


def test_markdown_and_json_share_report_id_and_layers(tmp_path) -> None:
    run = ScanRun(
        run_id="run-001",
        started_at=datetime.now(UTC),
        index_revision="rev-1",
        status="running",
    )
    builder = ReportBuilder(tmp_path)
    base = builder.write_base(run, Inventory(), Analysis())
    review = AgentReview(
        review_id="review-001",
        run_id=run.run_id,
        agent="codex",
        status=ReviewStatus.SKIPPED,
        schema_version="1",
        full_text_shared=False,
    )
    final = builder.append_review(base, review)
    markdown = final.bundle.markdown.read_text(encoding="utf-8")
    payload = json.loads(final.bundle.json_path.read_text(encoding="utf-8"))
    assert payload["report_id"] in markdown
    assert "确定性检查结论" in markdown
    assert "本地相似度分析" in markdown
    assert "Agent 语义复核" in markdown
    assert payload["agent_review"]["status"] == "skipped"
