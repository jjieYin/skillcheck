from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot
from skillcheck.governance.selection import AnalysisScope, ScopeSelector


def _root(
    root_id: str,
    path: Path,
    scope: RootScope,
    *,
    project_path: Path | None = None,
    enabled: bool = True,
) -> LibraryRoot:
    return LibraryRoot(
        root_id=root_id,
        path=path,
        provider="codex",
        scope=scope,
        project_path=project_path,
        enabled=enabled,
    )


def _snapshot(skill_id: str, root_id: str) -> SkillSnapshot:
    return SkillSnapshot(
        snapshot_id=f"snapshot-{skill_id}",
        skill_id=skill_id,
        root_id=root_id,
        relative_path=f"{skill_id}/SKILL.md",
        name=skill_id,
        body="A sufficiently complete skill body.",
        content_hash=f"sha256:{skill_id}",
        indexed_at=datetime(2026, 9, 27, tzinfo=UTC),
    )


def test_scope_selector_filters_all_global_project_and_custom_roots(tmp_path: Path) -> None:
    current_project = (tmp_path / "current").resolve()
    other_project = (tmp_path / "other").resolve()
    roots = [
        _root("global", tmp_path / "global", RootScope.GLOBAL),
        _root("project-current", tmp_path / "current-skills", RootScope.PROJECT, project_path=current_project),
        _root("project-other", tmp_path / "other-skills", RootScope.PROJECT, project_path=other_project),
        _root("custom", tmp_path / "custom", RootScope.CUSTOM),
        _root("disabled", tmp_path / "disabled", RootScope.GLOBAL, enabled=False),
    ]
    snapshots = [_snapshot(f"skill-{root.root_id}", root.root_id) for root in roots]
    selector = ScopeSelector()

    ids = lambda selected: {item.skill_id for item in selected}
    assert ids(selector.select_library(snapshots, roots, "all", project_path=current_project)) == {
        "skill-global", "skill-project-current", "skill-project-other", "skill-custom"
    }
    assert ids(selector.select_library(snapshots, roots, "global", project_path=current_project)) == {"skill-global"}
    assert ids(selector.select_library(snapshots, roots, "project", project_path=current_project)) == {
        "skill-project-current"
    }
    assert ids(selector.select_library(snapshots, roots, AnalysisScope.CUSTOM, project_path=current_project)) == {
        "skill-custom"
    }
    with pytest.raises(ValueError, match="scope"):
        selector.select_library(snapshots, roots, "unknown", project_path=current_project)


def test_project_scope_requires_a_current_project_path(tmp_path: Path) -> None:
    root = _root("project", tmp_path / "skills", RootScope.PROJECT, project_path=tmp_path)
    with pytest.raises(ValueError, match="project"):
        ScopeSelector().select_library([_snapshot("skill", "project")], [root], "project")


def test_source_selection_keeps_staged_skills_and_filters_catalog(tmp_path: Path) -> None:
    current_project = (tmp_path / "current").resolve()
    roots = [
        _root("global", tmp_path / "global", RootScope.GLOBAL),
        _root("project", tmp_path / "project", RootScope.PROJECT, project_path=current_project),
        _root("custom", tmp_path / "custom", RootScope.CUSTOM),
    ]
    catalog = [_snapshot("global-skill", "global"), _snapshot("project-skill", "project"), _snapshot("custom-skill", "custom")]
    staged = _snapshot("staged-skill", "staged")
    selector = ScopeSelector()

    selected = selector.select_catalog_for_source(catalog, roots, "project", project_path=current_project)

    assert {item.skill_id for item in selected} == {"project-skill"}
    assert {item.skill_id for item in [staged, *selected]} == {"staged-skill", "project-skill"}
