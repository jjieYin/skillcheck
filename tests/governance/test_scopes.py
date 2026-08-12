from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot
from skillcheck.governance import Relation
from skillcheck.governance.scopes import GovernanceScopeKey, ScopeClassifier


@dataclass(frozen=True)
class ScopeFixture:
    roots: list[LibraryRoot]
    same_root_copies: list[SkillSnapshot]
    cross_agent_copies: list[SkillSnapshot]
    similar_cross_agent: list[SkillSnapshot]


def _root(root_id: str, provider: str, path: Path) -> LibraryRoot:
    return LibraryRoot(
        root_id=root_id,
        path=path,
        provider=provider,
        scope=RootScope.PROJECT,
        project_path=path.parents[1],
    )


def _snapshot(skill_id: str, root_id: str, content_hash: str) -> SkillSnapshot:
    return SkillSnapshot(
        snapshot_id=f"snapshot-{skill_id}",
        skill_id=skill_id,
        root_id=root_id,
        relative_path=f"{skill_id}/SKILL.md",
        name=skill_id,
        content_hash=content_hash,
        indexed_at=datetime(2026, 8, 12, tzinfo=UTC),
    )


@pytest.fixture
def scope_fixture(tmp_path: Path) -> ScopeFixture:
    codex_root = _root("codex-project", "CoDeX", tmp_path / "project" / ".codex" / "skills")
    claude_root = _root("claude-project", "claude", tmp_path / "project" / ".claude" / "skills")
    return ScopeFixture(
        roots=[codex_root, claude_root],
        same_root_copies=[
            _snapshot("codex-copy-a", codex_root.root_id, "sha256:same-root"),
            _snapshot("codex-copy-b", codex_root.root_id, "sha256:same-root"),
        ],
        cross_agent_copies=[
            _snapshot("codex-copy", codex_root.root_id, "sha256:cross-agent"),
            _snapshot("claude-copy", claude_root.root_id, "sha256:cross-agent"),
        ],
        similar_cross_agent=[
            _snapshot("codex-similar", codex_root.root_id, "sha256:similar-a"),
            _snapshot("claude-similar", claude_root.root_id, "sha256:similar-b"),
        ],
    )


def test_governance_scope_key_normalizes_provider_and_project_path(tmp_path: Path) -> None:
    root = LibraryRoot(
        root_id="root-1",
        path=tmp_path / "skills",
        provider="CoDeX",
        scope=RootScope.PROJECT,
        project_path=tmp_path / "project" / ".." / "project",
    )

    assert GovernanceScopeKey.from_root(root) == GovernanceScopeKey(
        provider="codex",
        scope="project",
        project_path=str((tmp_path / "project").resolve()),
        root_id="root-1",
    )


def test_same_root_same_hash_is_exact_duplicate(scope_fixture: ScopeFixture) -> None:
    groups = ScopeClassifier(scope_fixture.roots).classify(scope_fixture.same_root_copies)

    assert [(group.relation, group.member_skill_ids) for group in groups] == [
        (Relation.EXACT_DUPLICATE, ["codex-copy-a", "codex-copy-b"])
    ]


def test_same_hash_across_agents_is_mirrored_copy(scope_fixture: ScopeFixture) -> None:
    groups = ScopeClassifier(scope_fixture.roots).classify(scope_fixture.cross_agent_copies)

    assert groups[0].relation is Relation.MIRRORED_COPY
    assert groups[0].requires_agent_judgment is False


def test_similar_but_non_identical_cross_agent_skills_are_not_auto_mirrors(
    scope_fixture: ScopeFixture,
) -> None:
    groups = ScopeClassifier(scope_fixture.roots).classify(scope_fixture.similar_cross_agent)

    assert all(group.relation is not Relation.MIRRORED_COPY for group in groups)
