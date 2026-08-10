from pathlib import Path

from skillcheck.catalog.ids import root_id, skill_id, snapshot_id


def test_root_id_is_stable_for_equivalent_paths(tmp_path) -> None:
    root = tmp_path / "skills"
    root.mkdir()

    assert root_id("codex", "global", root) == root_id(
        "codex", "global", root / ".." / "skills"
    )


def test_skill_id_ignores_absolute_parent_and_normalizes_relative_path() -> None:
    first = skill_id("codex", "project", Path("Review") / "SKILL.md")
    second = skill_id("codex", "project", "review/skill.md")

    assert first == second
    assert first.startswith("skill-")


def test_snapshot_id_changes_with_content_hash() -> None:
    identity = skill_id("codex", "global", "example/SKILL.md")

    assert snapshot_id(identity, "hash-one") != snapshot_id(identity, "hash-two")

