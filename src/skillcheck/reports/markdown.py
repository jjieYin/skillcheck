from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from skillcheck.reports.builder import ReportDocument


def render_markdown(document: ReportDocument) -> str:
    lines = [
        f"# SkillCheck 扫描报告：{document.report_id}",
        "",
        f"- 扫描运行：`{document.run_id}`",
        f"- Skill 数：`{document.skill_count}`",
        f"- 安装实例数：`{document.installation_count}`",
        f"- 唯一内容数：`{document.unique_skill_count}`",
        "",
        "## 确定性检查结论",
        "",
    ]
    if document.findings:
        lines.extend(f"- `{item.get('rule_id', 'unknown')}`：{item.get('message', '')}" for item in document.findings)
    else:
        lines.append("- 未发现确定性规则问题。")
    lines.extend(["", "## 本地相似度分析", ""])
    if document.groups:
        for group in document.groups:
            members = ", ".join(f"`{member}`" for member in group.get("member_skill_ids", []))
            lines.append(
                f"- `{group.get('relation', 'UNKNOWN')}` · {members}："
                f"{group.get('rule_suggestion', 'MANUAL_REVIEW')}"
            )
    else:
        lines.append("- 未发现需要分组处理的重复、重叠或冲突。")
    lines.extend(["", "## Agent 语义复核", ""])
    if document.agent_review is None:
        lines.append("- 尚未执行 Agent 复核。")
    else:
        lines.append(f"- Agent：`{document.agent_review.agent}`")
        lines.append(f"- 状态：`{document.agent_review.status.value}`")
        if document.agent_review.error:
            lines.append(f"- 降级原因：{document.agent_review.error}")
        for decision in document.agent_review.decisions:
            lines.append(
                f"- `{decision.group_id}`：`{decision.decision}`，置信度 `{decision.confidence:.2f}`，{decision.reason}"
            )
    lines.extend(["", "## 能力与限制", "", *[f"- {item}" for item in document.capabilities]])
    lines.extend(["- 报告仅提供建议；未自动删除、修改或覆盖已有 Skill。", ""])
    return "\n".join(lines)
