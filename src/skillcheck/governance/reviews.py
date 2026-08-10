from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from skillcheck.catalog.repository import CatalogRepository
from skillcheck.governance.reports import build_report
from skillcheck.governance.repository import GovernanceRepository
from skillcheck.models.governance import GroupDecision, SavedReview


class StaleAnalysisError(ValueError):
    """Raised when an Agent decision no longer matches the analyzed snapshots."""


class ReviewService:
    """Validate and store current-Agent governance decisions without touching Skills."""

    def __init__(self, catalog: CatalogRepository, reports_path: Path | str) -> None:
        self.catalog = catalog
        self.repository = GovernanceRepository(catalog)
        self.reports_path = Path(reports_path)

    def save(self, run_id: str, decisions: list[GroupDecision]) -> SavedReview:
        context = self.repository.review_context(run_id)
        self._validate(context, decisions)
        review_id = f"review-{uuid4().hex}"
        content = build_report(context, decisions)
        markdown_path = self.reports_path / f"{review_id}.md"
        json_path = self.reports_path / f"{review_id}.json"
        self._write_reports(markdown_path, json_path, content.markdown, content.json)
        try:
            self.repository.save_review(
                review_id=review_id,
                context=context,
                decisions=decisions,
                markdown_path=markdown_path,
                json_path=json_path,
                markdown=content.markdown,
                json_payload=content.json,
            )
        except Exception:
            markdown_path.unlink(missing_ok=True)
            json_path.unlink(missing_ok=True)
            raise
        return SavedReview(
            review_id=review_id,
            run_id=run_id,
            revision=context.revision,
            decisions=decisions,
            markdown_path=markdown_path,
            json_path=json_path,
        )

    @staticmethod
    def _validate(context, decisions: list[GroupDecision]) -> None:
        if not decisions:
            raise ValueError("at least one group decision is required")
        seen: set[str] = set()
        groups = {item.group_id: item for item in context.groups}
        for decision in decisions:
            if decision.group_id in seen:
                raise ValueError("at most one decision may be supplied for each group")
            seen.add(decision.group_id)
            group = groups.get(decision.group_id)
            if group is None:
                raise ValueError("group does not belong to analysis run")
            if decision.canonical_skill is not None and decision.canonical_skill not in group.member_skill_ids:
                raise ValueError("canonical_skill must belong to the current group")
        if not context.is_current:
            raise StaleAnalysisError("analysis snapshots have changed; analyze again before saving")

    @staticmethod
    def _write_reports(
        markdown_path: Path, json_path: Path, markdown: str, payload: dict[str, object]
    ) -> None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(markdown_path, markdown.encode("utf-8"))
        _atomic_write(
            json_path,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n",
        )


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def content_hash(content: str | bytes) -> str:
    """Return the database-safe hash for generated report bytes."""
    encoded = content.encode("utf-8") if isinstance(content, str) else content
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
