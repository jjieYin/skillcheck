import json
from pathlib import Path

from skillcheck.models import AuditGroup, LibraryAuditReport
from skillcheck.reports import ReportWriter
from tests.helpers import check_report


def test_markdown_and_json_share_decision(tmp_path: Path) -> None:
    paths = ReportWriter(tmp_path).write(check_report())
    markdown = paths.markdown.read_text(encoding="utf-8")
    payload = json.loads(paths.json.read_text(encoding="utf-8"))
    assert payload["decision"] == "MERGE"
    assert payload["report_id"] in markdown
    assert "建议：MERGE" in markdown


def test_audit_report_serializes_groups_and_no_changes_disclaimer(tmp_path: Path) -> None:
    report = LibraryAuditReport(
        report_id="SA-20260806-000000-deadbeef",
        scope="all",
        installation_count=3,
        unique_skill_count=2,
        groups=[
            AuditGroup(
                group_id="AG-exact-1",
                relation="EXACT_DUPLICATE",
                member_skill_ids=["a", "b"],
                confidence="high",
                recommendations=["保留一个副本"],
            )
        ],
        findings=[],
        capabilities=["hash-audit"],
    )
    paths = ReportWriter(tmp_path).write(report)
    payload = json.loads(paths.json.read_text(encoding="utf-8"))
    markdown = paths.markdown.read_text(encoding="utf-8")
    assert payload["groups"][0]["member_skill_ids"] == ["a", "b"]
    assert payload["relation_counts"]["EXACT_DUPLICATE"] == 1
    assert "未自动修改、删除或合并" in markdown
