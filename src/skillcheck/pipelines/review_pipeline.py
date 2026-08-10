"""Optional Agent semantic review orchestration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from skillcheck.models.review import AgentDecision, AgentReview, ReviewStatus
from skillcheck.reviewers.packet import build_packets
from skillcheck.reviewers.validation import validate_agent_output


class ReviewRepository:
    """Small repository facade; a database-backed repository can replace it."""

    def skipped(self, run_id: str, agent: str = "none") -> AgentReview:
        return AgentReview(
            review_id=f"review-{run_id}",
            run_id=run_id,
            agent=agent,
            status=ReviewStatus.SKIPPED,
            schema_version="1",
            full_text_shared=False,
        )

    def failed(self, run_id: str, agent: str, error: str) -> AgentReview:
        return AgentReview(
            review_id=f"review-{run_id}",
            run_id=run_id,
            agent=agent,
            status=ReviewStatus.FAILED,
            schema_version="1",
            full_text_shared=False,
            error=error,
        )

    def completed(self, run_id: str, agent: str, decisions: list[AgentDecision]) -> AgentReview:
        return AgentReview(
            review_id=f"review-{run_id}",
            run_id=run_id,
            agent=agent,
            status=ReviewStatus.COMPLETED,
            schema_version="1",
            full_text_shared=False,
            decisions=decisions,
        )


class ReviewPipeline:
    def __init__(
        self,
        adapters,
        validator: Callable[[str], Any] = validate_agent_output,
        repositories=None,
        packet_builder: Callable[..., list] = build_packets,
    ) -> None:
        self.adapters = adapters
        self.validator = validator
        self.repositories = repositories or type("Repositories", (), {"reviews": ReviewRepository()})()
        self.packet_builder = packet_builder

    def _repository(self) -> ReviewRepository:
        value = getattr(self.repositories, "reviews", self.repositories)
        return value

    def _adapter(self, mode: str):
        if hasattr(self.adapters, "get"):
            return self.adapters.get(mode)
        return self.adapters[mode]

    def review(self, run_id: str, groups, mode: str):
        normalized = getattr(mode, "value", mode)
        repository = self._repository()
        if normalized == "none":
            return repository.skipped(run_id, normalized)
        try:
            adapter = self._adapter(normalized)
        except (KeyError, ValueError):
            return repository.failed(run_id, normalized, f"{normalized} 复核未完成：Agent 未注册")
        capability = adapter.detect()
        if not capability.available:
            return repository.failed(
                run_id,
                normalized,
                f"{normalized.capitalize()} 复核未完成：{capability.reason or 'Agent 不可用'}",
            )
        try:
            packets = self.packet_builder(groups)
            decisions: list[AgentDecision] = []
            for packet in packets:
                execution = adapter.review(packet)
                if execution.returncode != 0 or execution.timed_out:
                    return repository.failed(
                        run_id,
                        normalized,
                        f"{normalized.capitalize()} 复核未完成：Agent 调用失败或超时",
                    )
                validated = self.validator(execution.stdout)
                decisions.extend(validated.groups)
            return repository.completed(run_id, normalized, decisions)
        except Exception as exc:  # noqa: BLE001 - review failures must degrade safely
            return repository.failed(
                run_id,
                normalized,
                f"{normalized.capitalize()} 复核未完成：{type(exc).__name__}",
            )

    def review_candidate(self, candidate, comparisons, mode: str):
        group = {
            "group_id": getattr(candidate, "skill_id", getattr(candidate, "content_hash", "candidate")),
            "relation": "MANUAL_REVIEW",
            "member_skill_ids": [getattr(item, "skill_id", str(item)) for item in comparisons],
            "evidence": comparisons,
        }
        run_id = getattr(candidate, "content_hash", "candidate-review")
        return self.review(run_id, [group], mode)
