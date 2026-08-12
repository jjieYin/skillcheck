"""Agent-native MCP facade for deterministic Skills governance."""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from skillcheck.governance.analyzer import GovernanceAnalyzer
from skillcheck.governance.models import AnalyzeMode, Relation, SyncPolicy
from skillcheck.governance.reviews import ReviewService
from skillcheck.governance.sync_groups import SyncGroupService
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
        trigger_source: str = "agent_intent",
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
        analyzer = self._governance()
        try:
            result = analyzer.analyze(
                selected_mode,
                source=source,
                scope=scope,
                limit=limit,
                trigger_source=trigger_source,
            )
        except TypeError as error:
            # Keep the facade compatible with injected v0.4 analyzers used by
            # integrations while the built-in analyzer records the source.
            if "trigger_source" not in str(error):
                raise
            result = analyzer.analyze(selected_mode, source=source, scope=scope, limit=limit)
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

    def save_sync_group(
        self,
        run_id: str,
        group_id: str,
        name: str,
        authority_skill_id: str,
        member_skill_ids: list[str],
        policy: str = "monitor_only",
    ) -> dict[str, object]:
        """Persist a user-confirmed, monitor-only group from current mirror evidence."""
        if not all(isinstance(value, str) and value for value in (run_id, group_id, name, authority_skill_id)):
            raise ValueError("run_id, group_id, name, and authority_skill_id are required")
        if policy != SyncPolicy.MONITOR_ONLY.value:
            raise ValueError("policy must be monitor_only")
        if not isinstance(member_skill_ids, list) or not all(
            isinstance(skill_id, str) and skill_id for skill_id in member_skill_ids
        ):
            raise ValueError("member_skill_ids must be a list of skill IDs")

        repository = self._governance().repository
        context = repository.review_context(run_id)
        candidate = next((item for item in context.groups if item.group_id == group_id), None)
        if candidate is None:
            raise ValueError("group does not belong to analysis run")
        if candidate.relation != Relation.MIRRORED_COPY.value:
            raise ValueError("group must have MIRRORED_COPY relation")
        requested_members = [authority_skill_id, *member_skill_ids]
        if set(requested_members) != set(candidate.member_skill_ids) or len(requested_members) != len(
            set(requested_members)
        ):
            raise ValueError("authority and member_skill_ids must match the analyzed group")
        if authority_skill_id not in candidate.member_skill_ids:
            raise ValueError("authority_skill_id must belong to the analyzed group")
        saved = SyncGroupService(repository).create_from_analysis(
            run_id=run_id,
            group_id=group_id,
            name=name,
            authority_skill_id=authority_skill_id,
            member_skill_ids=member_skill_ids,
        )
        return saved.model_dump(mode="json")

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
            self._reviews = ReviewService(self.runtime.repository, self.runtime.config.reports.directory)
        return self._reviews
