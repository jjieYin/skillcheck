from pathlib import Path

from skillcheck.catalog.discovery import discover_library_roots
from skillcheck.catalog.models import RootScope


def test_discovers_existing_global_project_and_custom_roots(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    global_root = home / ".codex" / "skills"
    project_root = project / ".agents" / "skills"
    custom_root = tmp_path / "custom-skills"
    for path in (global_root, project_root, custom_root):
        path.mkdir(parents=True)

    roots = discover_library_roots(home, project, custom_paths=[custom_root])

    by_path = {root.path: root for root in roots}
    assert set(by_path) == {global_root.resolve(), project_root.resolve(), custom_root.resolve()}
    assert by_path[global_root.resolve()].provider == "codex"
    assert by_path[global_root.resolve()].scope is RootScope.GLOBAL
    assert by_path[global_root.resolve()].project_path is None
    assert by_path[project_root.resolve()].provider == "agents"
    assert by_path[project_root.resolve()].scope is RootScope.PROJECT
    assert by_path[project_root.resolve()].project_path == project.resolve()
    assert by_path[custom_root.resolve()].provider == "custom"
    assert by_path[custom_root.resolve()].scope is RootScope.CUSTOM


def test_deduplicates_resolved_paths_and_skips_missing_directories(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    custom_root = tmp_path / "custom-skills"
    custom_root.mkdir(parents=True)
    duplicate = custom_root.parent / "." / custom_root.name

    roots = discover_library_roots(
        home,
        project,
        custom_paths=[custom_root, duplicate, tmp_path / "missing"],
    )

    assert len(roots) == 1
    assert roots[0].path == custom_root.resolve()
    assert roots[0].root_id.startswith("root-")
