"""Read-only query facade used by the MCP server and unit tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_PRIVATE_KEYS = {
    "body",
    "content",
    "full_text",
    "raw",
    "token",
    "api_key",
    "secret",
    "password",
    "source_text",
}


def _public(value: Any, *, key: str | None = None) -> Any:
    if key and key.casefold() in _PRIVATE_KEYS:
        return None
    if isinstance(value, Mapping):
        result = {}
        for name, item in value.items():
            if str(name).casefold() in _PRIVATE_KEYS:
                continue
            if str(name).casefold() == "sensitive" and bool(item):
                result["sensitive"] = True
                continue
            cleaned = _public(item, key=str(name))
            if cleaned is not None:
                result[str(name)] = cleaned
        return result
    if isinstance(value, (list, tuple, set)):
        return [_public(item) for item in value]
    if key and key.casefold() in {"excerpt", "value"} and isinstance(value, str) and len(value) > 500:
        return value[:500] + "…"
    return value


class SkillcheckQueries:
    """Small read-only facade over report/group repositories."""

    def __init__(self, repositories) -> None:
        self.repositories = repositories

    def summary(self) -> dict[str, object]:
        return _public(self.repositories.reports.latest_summary())

    def groups(
        self,
        *,
        relation: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        bounded = max(1, min(int(limit), 100))
        result = self.repositories.groups.list_public(relation=relation, limit=bounded)
        return [_public(item) for item in result]

    def report(self, report_id: str) -> dict[str, object]:
        if not report_id or len(report_id) > 200:
            raise ValueError("report_id 无效")
        return _public(self.repositories.reports.get_public(report_id))

