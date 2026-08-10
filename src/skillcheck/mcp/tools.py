"""Agent-native MCP facade for deterministic Skills governance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from skillcheck.governance.analyzer import GovernanceAnalyzer
from skillcheck.governance.models import AnalyzeMode
from skillcheck.governance.reviews import ReviewService
from skillcheck.mcp.runtime import McpRuntime
from skillcheck.models.governance import GroupDecision


class SkillcheckMcpTools:
    """Expose bounded local analysis; the connected Agent supplies judgment."""

    def __init__(
        self,
        runtime: McpRuntime,
        *,
        analyzer: GovernanceAnalyzer | None = None,
        reviews: ReviewService | None = None,
    ) -> None:
        self.runtime = runtime
        self._analyzer = analyzer
        self._reviews = reviews

    def analyze(
        self,
        mode: str,
        source: str | None = None,
        scope: str = "all",
        limit: int = 20,
    ) -> dict[str, object]:
        try:
            selected_mode = AnalyzeMode(mode)
        except ValueError as error:
            raise ValueError("mode must be 'library' or 'source'") from error
        if selected_mode is AnalyzeMode.SOURCE and not source:
            raise ValueError("source mode requires a source")
        if selected_mode is AnalyzeMode.LIBRARY and source:
            raise ValueError("library mode does not accept a source")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        self.runtime.before_query()
        result = self._governance().analyze(
            selected_mode, source=source, scope=scope, limit=limit
        )
        return result.model_dump(mode="json")

    def evidence(
        self,
        run_id: str,
        group_id: str,
        page: int = 0,
        include_body: bool = False,
    ) -> dict[str, object]:
        if not run_id or not group_id:
            raise ValueError("run_id and group_id are required")
        if isinstance(page, bool) or not isinstance(page, int) or page < 0:
            raise ValueError("page must be non-negative")
        result = self._governance().evidence(
            run_id, group_id, page=page + 1, include_body=bool(include_body)
        )
        return result.model_dump(mode="json")

    def save_review(self, run_id: str, decisions: list[dict[str, Any]]) -> dict[str, object]:
        if not run_id:
            raise ValueError("run_id is required")
        parsed = TypeAdapter(list[GroupDecision]).validate_python(decisions)
        result = self._review_service().save(run_id, parsed)
        return result.model_dump(mode="json")

    def _governance(self) -> GovernanceAnalyzer:
        if self._analyzer is None:
            if self.runtime.repository is None:
                raise RuntimeError("Skill catalog is not initialized; run 'skillcheck init' first")
            self._analyzer = GovernanceAnalyzer(self.runtime.repository, runtime=self.runtime)
        return self._analyzer

    def _review_service(self) -> ReviewService:
        if self._reviews is None:
            if self.runtime.repository is None:
                raise RuntimeError("Skill catalog is not initialized; run 'skillcheck init' first")
            self._reviews = ReviewService(self.runtime.repository, Path(self.runtime.config.reports_path))
        return self._reviews
