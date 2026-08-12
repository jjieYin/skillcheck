from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.governance import GovernanceAnalyzer, Relation
from skillcheck.governance.models import AnalyzeMode
from skillcheck.governance.reviews import StaleAnalysisError
from skillcheck.mcp.tools import SkillcheckMcpTools
from skillcheck.models.governance import GovernanceDecision, GroupDecision


class Analyzer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def analyze(self, mode, *, source=None, scope="all", trigger_source="agent_intent"):
        self.calls.append(("analyze", (mode, source, scope, trigger_source)))
        return SimpleNamespace(model_dump=lambda **_: {"mode": str(mode), "source": source})

    def evidence(self, run_id, group_id, *, page=1, include_body=False):
        self.calls.append(("evidence", (run_id, group_id, page, include_body)))
        return SimpleNamespace(model_dump=lambda **_: {"run_id": run_id, "group_id": group_id, "page": page})


class Reviews:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[GroupDecision]]] = []

    def save(self, run_id, decisions):
        self.calls.append((run_id, decisions))
        return SimpleNamespace(model_dump=lambda **_: {"run_id": run_id, "saved": len(decisions)})


def _tools() -> tuple[SkillcheckMcpTools, Analyzer, Reviews, list[str]]:
    calls: list[str] = []
    analyzer = Analyzer()
    reviews = Reviews()
    runtime = SimpleNamespace(before_query=lambda: calls.append("before_query"))
    return SkillcheckMcpTools(runtime, analyzer=analyzer, reviews=reviews), analyzer, reviews, calls


def _snapshot(skill_id: str, root_id: str, content_hash: str) -> SkillSnapshot:
    return SkillSnapshot(
        snapshot_id=f"snapshot-{skill_id}-{content_hash.rsplit(':', 1)[-1]}",
        skill_id=skill_id,
        root_id=root_id,
        relative_path=f"{skill_id}/SKILL.md",
        name=skill_id,
        description="An API review skill.",
        body="Review API contracts and validate their request fields.",
        content_hash=content_hash,
        indexed_at=datetime(2026, 8, 12, tzinfo=UTC),
    )


@pytest.fixture
def mirror_run(tmp_path):
    database = CatalogDatabase(tmp_path / "catalog.db")
    database.initialize()
    catalog = CatalogRepository(database)
    for root_id, provider in (("codex-root", "codex"), ("claude-root", "claude")):
        catalog.upsert_root(
            LibraryRoot(
                root_id=root_id,
                path=tmp_path / root_id,
                provider=provider,
                scope=RootScope.GLOBAL,
            )
        )
    catalog.upsert_snapshot(_snapshot("codex-api", "codex-root", "sha256:mirror"))
    catalog.upsert_snapshot(_snapshot("claude-api", "claude-root", "sha256:mirror"))
    analyzer = GovernanceAnalyzer(catalog)
    result = analyzer.analyze_library(limit=20)
    group = next(group for group in result.groups if group.relation is Relation.MIRRORED_COPY)
    return SimpleNamespace(catalog=catalog, result=result, group=group)


@pytest.fixture
def mcp_tools(mirror_run) -> SkillcheckMcpTools:
    runtime = SimpleNamespace(repository=mirror_run.catalog)
    return SkillcheckMcpTools(runtime, analyzer=GovernanceAnalyzer(mirror_run.catalog))


@pytest.fixture
def stale_mirror_run(mirror_run):
    mirror_run.catalog.upsert_snapshot(
        _snapshot("codex-api", "codex-root", "sha256:changed")
    )
    return SimpleNamespace(run_id=mirror_run.result.run_id, group_id=mirror_run.group.group_id)


def test_analyze_validates_source_mode_and_returns_json() -> None:
    tools, analyzer, _, calls = _tools()

    result = tools.analyze("library")

    assert result == {"mode": str(AnalyzeMode.LIBRARY), "source": None}
    assert calls == ["before_query"]
    assert analyzer.calls == [("analyze", (AnalyzeMode.LIBRARY, None, "all", "agent_intent"))]
    with pytest.raises(ValueError, match="source"):
        tools.analyze("source")
    with pytest.raises(ValueError, match="mode"):
        tools.analyze("unknown")


def test_library_analysis_defaults_to_full_catalog() -> None:
    tools, analyzer, _, calls = _tools()

    tools.analyze("library")

    assert calls == ["before_query"]
    assert analyzer.calls == [("analyze", (AnalyzeMode.LIBRARY, None, "all", "agent_intent"))]


def test_source_analysis_keeps_a_bounded_default() -> None:
    tools, analyzer, _, _ = _tools()

    tools.analyze("source", "incoming-skill")

    assert analyzer.calls == [("analyze", (AnalyzeMode.SOURCE, "incoming-skill", "all", "agent_intent"))]


def test_evidence_validates_page_and_returns_json() -> None:
    tools, analyzer, _, calls = _tools()

    result = tools.evidence("run-1", "group-1", 0, True)

    assert result == {"run_id": "run-1", "group_id": "group-1", "page": 1}
    assert analyzer.calls == [("evidence", ("run-1", "group-1", 1, True))]
    assert calls == []
    with pytest.raises(ValueError, match="page"):
        tools.evidence("run-1", "group-1", -1, False)


def test_save_review_rejects_malformed_decisions_and_serializes_saved_review() -> None:
    tools, _, reviews, calls = _tools()
    decision = {
        "group_id": "group-1",
        "decision": GovernanceDecision.MERGE.value,
        "canonical_skill": "skill-1",
        "confidence": 0.9,
        "reason": "The documented responsibilities overlap.",
        "recommendations": ["Merge the shared steps."],
    }

    assert tools.save_review("run-1", [decision]) == {"run_id": "run-1", "saved": 1}
    assert calls == []
    assert reviews.calls[0][0] == "run-1"
    assert reviews.calls[0][1][0].decision is GovernanceDecision.MERGE
    with pytest.raises(ValueError):
        tools.save_review("run-1", [{"group_id": "missing-required-fields"}])


def test_save_sync_group_persists_confirmed_mirror_baseline(mcp_tools, mirror_run) -> None:
    saved = mcp_tools.save_sync_group(
        run_id=mirror_run.result.run_id,
        group_id=mirror_run.group.group_id,
        name="api-review",
        authority_skill_id="codex-api",
        member_skill_ids=["claude-api"],
        policy="monitor_only",
    )

    assert saved["name"] == "api-review"
    assert saved["authority_skill_id"] == "codex-api"
    assert saved["policy"] == "monitor_only"
    assert [member["skill_id"] for member in saved["members"]] == ["codex-api", "claude-api"]
    assert mirror_run.catalog.get_current_skill("codex-api").content_hash == "sha256:mirror"


def test_save_sync_group_rejects_stale_analysis(mcp_tools, stale_mirror_run) -> None:
    with pytest.raises(StaleAnalysisError):
        mcp_tools.save_sync_group(
            run_id=stale_mirror_run.run_id,
            group_id=stale_mirror_run.group_id,
            name="api-review",
            authority_skill_id="codex-api",
            member_skill_ids=["claude-api"],
            policy="monitor_only",
        )


def test_save_sync_group_rechecks_snapshot_in_its_write_transaction(
    mcp_tools, mirror_run, monkeypatch
) -> None:
    from skillcheck.governance.sync_groups import SyncGroupService

    original = SyncGroupService.create_from_analysis

    def stale_before_transaction(self, *args, **kwargs):
        mirror_run.catalog.upsert_snapshot(
            _snapshot("codex-api", "codex-root", "sha256:changed-after-validation")
        )
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SyncGroupService, "create_from_analysis", stale_before_transaction)

    with pytest.raises(StaleAnalysisError):
        mcp_tools.save_sync_group(
            run_id=mirror_run.result.run_id,
            group_id=mirror_run.group.group_id,
            name="api-review",
            authority_skill_id="codex-api",
            member_skill_ids=["claude-api"],
        )

def test_save_sync_group_rejects_deleted_member_as_stale(mcp_tools, mirror_run) -> None:
    with mirror_run.catalog.database.connect() as connection:
        connection.execute(
            "UPDATE skills SET current_snapshot_id = NULL, status = 'missing' WHERE skill_id = ?",
            ("claude-api",),
        )

    with pytest.raises(StaleAnalysisError):
        mcp_tools.save_sync_group(
            run_id=mirror_run.result.run_id,
            group_id=mirror_run.group.group_id,
            name="api-review",
            authority_skill_id="codex-api",
            member_skill_ids=["claude-api"],
        )
