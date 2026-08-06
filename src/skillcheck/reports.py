from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from skillcheck.models import CheckReport, LibraryAuditReport


@dataclass(frozen=True)
class ReportPaths:
    markdown: Path
    json: Path


class ReportWriter:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, report: CheckReport | LibraryAuditReport) -> ReportPaths:
        if isinstance(report, CheckReport):
            payload = report.model_dump(mode="json")
            markdown = _render_check(report)
        elif isinstance(report, LibraryAuditReport):
            payload = report.model_dump(mode="json")
            payload["relation_counts"] = dict(Counter(group.relation for group in report.groups))
            markdown = _render_audit(report)
        else:
            raise TypeError(f"unsupported report type: {type(report)!r}")
        payload["report_type"] = "check" if isinstance(report, CheckReport) else "audit"
        json_text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        markdown_path = self.root / f"{report.report_id}.md"
        json_path = self.root / f"{report.report_id}.json"
        _atomic_write(markdown_path, markdown)
        _atomic_write(json_path, json_text)
        return ReportPaths(markdown=markdown_path, json=json_path)

    def latest(self) -> ReportPaths | None:
        markdown_files = sorted(self.root.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not markdown_files:
            return None
        markdown = markdown_files[0]
        return ReportPaths(markdown=markdown, json=markdown.with_suffix(".json"))

    def find(self, report_id: str) -> ReportPaths:
        markdown = self.root / f"{report_id}.md"
        json_path = self.root / f"{report_id}.json"
        if not markdown.is_file() or not json_path.is_file():
            raise FileNotFoundError(f"report not found: {report_id}")
        return ReportPaths(markdown=markdown, json=json_path)


def make_check_report_id(source_hash: str, now: datetime | None = None) -> str:
    return f"SC-{(now or datetime.now(UTC)).strftime('%Y%m%d-%H%M%S')}-{_short_hash(source_hash)}"


def make_audit_report_id(scope: str, groups: list[str], now: datetime | None = None) -> str:
    digest = hashlib.sha256(f"{scope}|{'|'.join(sorted(groups))}".encode()).hexdigest()
    return f"SA-{(now or datetime.now(UTC)).strftime('%Y%m%d-%H%M%S')}-{digest[:8]}"


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _render_check(report: CheckReport) -> str:
    lines = [
        f"# SkillCheck 检查报告：{report.report_id}",
        "",
        f"- 决策：`{report.decision.value}`",
        f"- 置信度：`{report.confidence}`",
        f"- 是否阻断安装：`{'是' if report.blocking else '否'}`",
        f"- 来源：`{report.source}`",
        f"- 来源哈希：`{report.source_hash}`",
        "",
        f"## 建议：{report.decision.value}",
        "",
        *[f"- {recommendation}" for recommendation in report.recommendations],
        "",
        "## 候选 Skill",
        "",
    ]
    if report.candidates:
        lines.extend(
            f"- `{candidate.skill.skill_id}`：相似度 {candidate.similarity:.3f}，关系 `{candidate.relation.value}`"
            for candidate in report.candidates
        )
    else:
        lines.append("- 无候选或检索能力未启用。")
    lines.extend(["", "## 检查发现", ""])
    if report.findings:
        lines.extend(
            f"- `{finding.rule_id}` [{finding.severity.value}] {finding.message}（整改：{finding.remediation}）"
            for finding in report.findings
        )
    else:
        lines.append("- 未发现确定性规则问题。")
    lines.extend(
        [
            "",
            "## 能力与限制",
            "",
            *[f"- {capability}" for capability in report.capabilities],
            "- 报告仅提供建议；未自动删除、修改或覆盖已有 Skill。",
            "",
        ]
    )
    return "\n".join(lines)


def _render_audit(report: LibraryAuditReport) -> str:
    lines = [
        f"# SkillCheck 已有 Skill 库审计报告：{report.report_id}",
        "",
        f"- 审计范围：`{report.scope}`",
        f"- 安装实例数：`{report.installation_count}`",
        f"- 唯一内容数：`{report.unique_skill_count}`",
        f"- LLM 复核：`{'是' if report.llm_used else '否'}`",
        "",
        "## 分组结果",
        "",
    ]
    if report.groups:
        for group in report.groups:
            lines.extend(
                [
                    f"### {group.relation} · `{group.group_id}`",
                    f"成员：{', '.join(f'`{member}`' for member in group.member_skill_ids)}",
                    f"置信度：`{group.confidence}`",
                ]
            )
            lines.extend(f"- 证据：{item}" for item in group.same_points)
            lines.extend(f"- 建议：{item}" for item in group.recommendations)
            lines.append("")
    else:
        lines.extend(["- 未发现需要分组处理的重复、重叠或冲突。", ""])
    lines.extend(["## 能力与限制", ""])
    lines.extend(f"- {capability}" for capability in report.capabilities)
    lines.extend(
        [
            "- 本报告仅输出治理建议，未自动修改、删除或合并任何 Skill。",
            "",
        ]
    )
    return "\n".join(lines)
