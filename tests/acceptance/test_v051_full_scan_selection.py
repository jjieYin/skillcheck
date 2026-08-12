from __future__ import annotations

from pathlib import Path

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.models import LibraryRoot, RootScope
from skillcheck.catalog.reconcile import CatalogReconciler
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.config import load_config
from skillcheck.governance.analyzer import GovernanceAnalyzer
from skillcheck.pipelines.install_pipeline import InstallPipeline
from skillcheck.targets.base import AgentId
from skillcheck.targets.codex import CodexTarget
from skillcheck.targets.cursor import CursorTarget
from skillcheck.targets.registry import TargetRegistry


def _write_skill(root: Path, index: int) -> None:
    directory = root / f"skill-{index:03d}"
    directory.mkdir(parents=True)
    if index in {160, 167}:
        name = "shared-duplicate"
        description = "The same implementation appears in two locations."
        body = "Run the shared duplicate procedure safely."
    else:
        name = f"skill-{index:03d}"
        description = f"Perform task {index}."
        body = f"Run task {index} safely."
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )


def _install_pipeline(root: Path) -> InstallPipeline:
    options = {
        "global_config": root / "codex" / "config.toml",
        "project_config": root / "project" / "codex" / "config.toml",
        "global_instructions": root / "codex" / "AGENTS.md",
        "project_instructions": root / "project" / "codex" / "AGENTS.md",
    }
    codex = CodexTarget(**options)
    cursor = CursorTarget(
        global_config=root / "cursor" / "mcp.json",
        project_config=root / "project" / "cursor" / "mcp.json",
        global_instructions=root / "cursor" / "rules" / "skillcheck.mdc",
        project_instructions=root / "project" / "cursor" / "rules" / "skillcheck.mdc",
    )
    return InstallPipeline(
        TargetRegistry([codex, cursor]),
        smoke_check=lambda: "smoke passed",
    )


def test_v051_full_scan_and_exact_agent_reselection(tmp_path: Path) -> None:
    library = tmp_path / "skills"
    for index in range(168):
        _write_skill(library, index)

    config_path = tmp_path / "state" / "config.yaml"
    config = load_config(config_path, home=tmp_path, create=False)
    config.catalog.database_path = tmp_path / "state" / "index.db"
    config.catalog.roots = [library]
    config.catalog.initialized = True
    CatalogDatabase(config.catalog.database_path).initialize()
    repository = CatalogRepository(CatalogDatabase(config.catalog.database_path))
    CatalogReconciler(repository).reconcile(
        [
            LibraryRoot(
                root_id="custom-test-library",
                path=library,
                provider="custom",
                scope=RootScope.CUSTOM,
            )
        ]
    )
    analysis = GovernanceAnalyzer(repository).analyze_library()

    assert analysis.summary.skills_considered == 168
    current = {
        item.relative_path: item
        for item in repository.list_current_skills()
    }
    assert any(
        set(group.member_skill_ids) >= {
            current["skill-160/SKILL.md"].skill_id,
            current["skill-167/SKILL.md"].skill_id,
        }
        for group in analysis.groups
    )

    pipeline = _install_pipeline(tmp_path)
    first = pipeline.preview_reconcile([], ["codex", "cursor"], scope="global")
    pipeline.apply_reconcile(first, confirmed=True)
    second = pipeline.preview_reconcile(["codex", "cursor"], ["codex"], scope="global")
    assert second.added == []
    assert second.kept == ["codex"]
    assert second.removed == ["cursor"]
    pipeline.apply_reconcile(second, confirmed=True)
    assert pipeline.registry.get(AgentId.CODEX).validate("global")
    assert pipeline.registry.get(AgentId.CURSOR).validate_absent("global")
