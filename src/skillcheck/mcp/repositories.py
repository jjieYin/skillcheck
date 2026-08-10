"""Minimal filesystem repositories for local report-backed MCP queries."""

from __future__ import annotations

import json
from pathlib import Path


def _read_report(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FileNotFoundError(f"报告不可读：{path}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"报告根节点不是对象：{path}")
    return payload


class FileReportRepository:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser()

    def _latest_path(self) -> Path | None:
        paths = sorted(
            self.root.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        return paths[0] if paths else None

    def latest_summary(self) -> dict[str, object]:
        path = self._latest_path()
        if path is None:
            return {"report_id": None, "skill_count": 0, "group_count": 0, "findings": []}
        payload = _read_report(path)
        groups = payload.get("groups", [])
        findings = payload.get("findings", [])
        return {
            "report_id": payload.get("report_id", path.stem),
            "skill_count": payload.get("skill_count", payload.get("unique_skill_count", 0)),
            "installation_count": payload.get("installation_count", 0),
            "group_count": len(groups) if isinstance(groups, list) else 0,
            "finding_count": len(findings) if isinstance(findings, list) else 0,
        }

    def get_public(self, report_id: str) -> dict[str, object]:
        path = self.root / f"{report_id}.json"
        if not path.is_file():
            raise FileNotFoundError(f"报告不存在：{report_id}")
        return _read_report(path)


class FileGroupRepository:
    def __init__(self, reports: FileReportRepository) -> None:
        self.reports = reports

    def list_public(self, *, relation: str | None, limit: int) -> list[dict[str, object]]:
        path = self.reports._latest_path()
        if path is None:
            return []
        payload = _read_report(path)
        groups = payload.get("groups", [])
        if not isinstance(groups, list):
            return []
        result = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            if relation and group.get("relation") != relation:
                continue
            evidence = group.get("evidence") or group.get("same_points") or []
            result.append(
                {
                    "group_id": group.get("group_id"),
                    "relation": group.get("relation"),
                    "member_skill_ids": group.get("member_skill_ids", []),
                    "similarity": group.get("similarity", group.get("confidence")),
                    "evidence": evidence,
                    "recommendations": group.get("recommendations", []),
                }
            )
            if len(result) >= limit:
                break
        return result


class FileRepositories:
    def __init__(self, reports_path: Path) -> None:
        self.reports = FileReportRepository(reports_path)
        self.groups = FileGroupRepository(self.reports)
