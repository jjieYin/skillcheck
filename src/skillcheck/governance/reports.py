from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from skillcheck.models.governance import GroupDecision

from .redaction import redact_value

if TYPE_CHECKING:
    from skillcheck.governance.repository import ReviewContext


@dataclass(frozen=True)
class ReportContent:
    markdown: str
    json: dict[str, object]


def build_report(context: ReviewContext, decisions: list[GroupDecision]) -> ReportContent:
    """Render the public, credential-free record of a governance review."""
    groups = [
        {
            "group_id": group.group_id,
            "relation": group.relation,
            "similarity": group.similarity,
            "snapshot_ids": group.snapshot_ids,
            "member_skill_ids": group.member_skill_ids,
        }
        for group in context.groups
    ]
    rendered_decisions = [redact_value(item.model_dump(mode="json")) for item in decisions]
    payload: dict[str, object] = {
        "run_id": context.run_id,
        "revision": context.revision,
        "snapshot_ids": sorted({snapshot for group in groups for snapshot in group["snapshot_ids"]}),
        "local_findings": redact_value(context.local_findings),
        "groups": groups,
        "agent_decisions": rendered_decisions,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    candidate_lines = [
        f"- `{group.group_id}`：{group.relation}；成员：{', '.join(group.member_skill_ids)}"
        for group in context.groups
    ] or ["- 未发现需要 Agent 复核的候选组。"]
    decision_lines = [
        f"- `{item.group_id}`：{item.decision.value}（置信度 {item.confidence:.0%}）——{item.reason}"
        for item in decisions
    ] or ["- 本次没有保存 Agent 决策。"]
    action_lines = [
        f"- `{item.group_id}`：{'；'.join(item.recommendations) or '请按上述判断人工处理。'}"
        for item in decisions
    ] or ["- 请保留现有 Skill 文件，待人工确认后再操作。"]
    local_lines = [
        f"- 本次分析版本：`{context.revision}`；已校验 {len(context.groups)} 个候选组。"
    ]

    markdown = "\n".join(
        [
            "# Skillcheck 治理报告",
            "## 本地确定性问题",
            *local_lines,
            "## 相似候选与证据",
            *candidate_lines,
            "## Agent 语义判断",
            *decision_lines,
            "## 建议的人工操作",
            *action_lines,
            "## 安全边界",
            "- 本报告只保存目录索引、候选关系和 Agent 决策；不会写入、删除或重命名任何用户 Skill 文件。",
            "- 报告不包含 Skill 正文、凭据或 Agent 的隐藏配置。",
            "",
        ]
    )
    return ReportContent(markdown=markdown, json=payload)
