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

from .redaction import redact_text


class StaleAnalysisError(ValueError):
    """Raised when an Agent decision no longer matches the analyzed snapshots."""


class ReviewService:
    """Validate and store current-Agent governance decisions without touching Skills."""

    def __init__(self, catalog: CatalogRepository, reports_path: Path | str) -> None:
        self.catalog = catalog
        self.repository = GovernanceRepository(catalog)
        candidate = Path(reports_path).expanduser().resolve(strict=False)
        allowed = (catalog.database.path.expanduser().resolve(strict=False).parent / "reports").resolve(
            strict=False
        )
        if candidate != allowed and allowed not in candidate.parents:
            raise ValueError("report directory must remain inside the Skillcheck catalog report area")
        self.reports_path = candidate

    def save(self, run_id: str, decisions: list[GroupDecision]) -> SavedReview:
        context = self.repository.review_context(run_id)
        self._validate(context, decisions)
        decisions = [
            item.model_copy(
                update={
                    "reason": redact_text(item.reason),
                    "recommendations": [redact_text(value) for value in item.recommendations],
                }
            )
            for item in decisions
        ]
        review_id = f"review-{uuid4().hex}"
        content = build_report(context, decisions)
        markdown_path = self.reports_path / f"{review_id}.md"
        json_path = self.reports_path / f"{review_id}.json"
        markdown_bytes = content.markdown.encode("utf-8")
        json_bytes = (
            json.dumps(content.json, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        )
        self._publish_reports(
            markdown_path,
            json_path,
            markdown_bytes,
            json_bytes,
        )
        try:
            self.repository.save_review(
                review_id=review_id,
                context=context,
                decisions=decisions,
                markdown_path=markdown_path,
                json_path=json_path,
                markdown=content.markdown,
                json_payload=content.json,
                markdown_bytes=markdown_bytes,
                json_bytes=json_bytes,
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
    def _publish_reports(
        markdown_path: Path,
        json_path: Path,
        markdown_bytes: bytes,
        json_bytes: bytes,
    ) -> None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        staged: list[tuple[Path, Path]] = []
        published: list[Path] = []
        try:
            for path, content in ((markdown_path, markdown_bytes), (json_path, json_bytes)):
                staged.append((_stage_file(path, content), path))
            for temporary, destination in staged:
                os.replace(temporary, destination)
                published.append(destination)
        except Exception:
            for temporary, _destination in staged:
                temporary.unlink(missing_ok=True)
            for destination in published:
                destination.unlink(missing_ok=True)
            raise


def _stage_file(path: Path, content: bytes) -> Path:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        return temporary
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def content_hash(content: str | bytes) -> str:
    """Return the database-safe hash for generated report bytes."""
    encoded = content.encode("utf-8") if isinstance(content, str) else content
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
