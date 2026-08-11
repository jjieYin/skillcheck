from pathlib import Path

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.ids import skill_id
from skillcheck.catalog.models import LibraryRoot, RootScope, SkillStatus
from skillcheck.catalog.reconcile import CatalogReconciler
from skillcheck.catalog.repository import CatalogRepository


def _write_skill(root: LibraryRoot, name: str = "Example", description: str = "first") -> Path:
    skill = root.path / "example"
    skill.mkdir(parents=True)
    path = skill / "SKILL.md"
    path.write_text(f"---\nname: {name}\ndescription: {description}\n---\nBody\n", encoding="utf-8")
    return path


def _root(tmp_path: Path) -> LibraryRoot:
    path = tmp_path / "skills"
    path.mkdir()
    return LibraryRoot(
        root_id="root-1", path=path, provider="codex", scope=RootScope.PROJECT
    )


def _reconciler(tmp_path: Path) -> tuple[CatalogRepository, CatalogReconciler]:
    database = CatalogDatabase(tmp_path / "catalog.db")
    database.initialize()
    repository = CatalogRepository(database)
    return repository, CatalogReconciler(repository)


def test_reconcile_adds_then_updates_a_skill_snapshot(tmp_path: Path) -> None:
    root = _root(tmp_path)
    path = _write_skill(root)
    repository, reconciler = _reconciler(tmp_path)

    added = reconciler.reconcile([root])
    original = repository.list_current_skills()[0]
    path.write_text("---\nname: Example\ndescription: changed\n---\nNew body\n", encoding="utf-8")
    updated = reconciler.reconcile([root])

    current = repository.list_current_skills()[0]
    assert (added.added, added.updated) == (1, 0)
    assert (updated.added, updated.updated) == (0, 1)
    assert current.description == "changed"
    assert current.snapshot_id != original.snapshot_id
    assert len(repository.list_snapshots(current.skill_id)) == 2


def test_reconcile_discovers_skills_at_arbitrary_depth(tmp_path: Path) -> None:
    root = _root(tmp_path)
    nested = root.path / "prd-ux-code" / "opt" / "visual" / "deep-skill"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text(
        "---\nname: deep-skill\ndescription: nested\n---\nBody\n",
        encoding="utf-8",
    )
    repository, reconciler = _reconciler(tmp_path)

    summary = reconciler.reconcile([root])

    assert summary.added == 1
    skills = repository.list_current_skills()
    assert len(skills) == 1
    assert skills[0].relative_path == "prd-ux-code/opt/visual/deep-skill/SKILL.md"


def test_reconcile_marks_deleted_skill_missing_without_deleting_history(tmp_path: Path) -> None:
    root = _root(tmp_path)
    path = _write_skill(root)
    repository, reconciler = _reconciler(tmp_path)

    reconciler.reconcile([root])
    current = repository.list_current_skills()[0]
    path.unlink()
    path.parent.rmdir()
    summary = reconciler.reconcile([root])

    missing = repository.get_current_skill(current.skill_id)
    assert summary.removed == 1
    assert missing is not None
    assert missing.status is SkillStatus.MISSING
    assert len(repository.list_snapshots(current.skill_id)) == 1


def test_reconcile_restores_deleted_skill_with_the_same_content(tmp_path: Path) -> None:
    root = _root(tmp_path)
    path = _write_skill(root)
    original_content = path.read_text(encoding="utf-8")
    repository, reconciler = _reconciler(tmp_path)

    reconciler.reconcile([root])
    path.unlink()
    path.parent.rmdir()
    reconciler.reconcile([root])
    path.parent.mkdir()
    path.write_text(original_content, encoding="utf-8")
    summary = reconciler.reconcile([root])

    restored = repository.get_current_skill(skill_id("codex", "project", "example/SKILL.md"))
    assert summary.updated == 1
    assert restored is not None
    assert restored.status is SkillStatus.ACTIVE


def test_reconcile_records_invalid_skill_and_continues_other_files(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _write_skill(root)
    invalid = root.path / "broken"
    invalid.mkdir()
    (invalid / "SKILL.md").write_bytes(b"---\nname: \xff\n---\n")
    repository, reconciler = _reconciler(tmp_path)

    summary = reconciler.reconcile([root])

    skills = repository.list_current_skills()
    assert summary.invalid == 1
    assert len(skills) == 1
    invalid_snapshot = repository.get_current_skill(skill_id("codex", "project", "broken/SKILL.md"))
    assert invalid_snapshot is not None
    assert invalid_snapshot.status is SkillStatus.INVALID
    assert invalid_snapshot.parse_error


def test_reconcile_changed_paths_only_reprocesses_the_affected_skill(tmp_path: Path) -> None:
    root = _root(tmp_path)
    first = _write_skill(root)
    second = root.path / "other" / "SKILL.md"
    second.parent.mkdir()
    second.write_text("---\nname: Other\n---\nBody\n", encoding="utf-8")
    repository, reconciler = _reconciler(tmp_path)
    reconciler.reconcile([root])
    before = {skill.name: skill.snapshot_id for skill in repository.list_current_skills()}
    first.write_text("---\nname: Example\ndescription: changed\n---\nBody\n", encoding="utf-8")

    summary = reconciler.reconcile([root], changed_paths=[first])

    after = {skill.name: skill.snapshot_id for skill in repository.list_current_skills()}
    assert summary.updated == 1
    assert after["Example"] != before["Example"]
    assert after["Other"] == before["Other"]


def test_reconcile_asset_change_updates_the_skill_snapshot(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _write_skill(root)
    asset = root.path / "example" / "reference.txt"
    asset.write_text("first", encoding="utf-8")
    repository, reconciler = _reconciler(tmp_path)
    reconciler.reconcile([root])
    before = repository.list_current_skills()[0].snapshot_id
    asset.write_text("changed asset", encoding="utf-8")

    summary = reconciler.reconcile([root], changed_paths=[asset])

    assert summary.updated == 1
    assert repository.list_current_skills()[0].snapshot_id != before


def test_reconcile_relative_deleted_changed_path_marks_skill_missing(tmp_path: Path) -> None:
    root = _root(tmp_path)
    path = _write_skill(root)
    repository, reconciler = _reconciler(tmp_path)
    reconciler.reconcile([root])
    path.unlink()
    path.parent.rmdir()

    summary = reconciler.reconcile([root], changed_paths=[Path("example/SKILL.md")])

    current = repository.get_current_skill(skill_id("codex", "project", "example/SKILL.md"))
    assert summary.removed == 1
    assert current is not None
    assert current.status is SkillStatus.MISSING


def test_reconcile_cwd_relative_changed_path_updates_skill(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    root_path = project / ".codex" / "skills"
    root_path.mkdir(parents=True)
    root = LibraryRoot(root_id="root-1", path=root_path, provider="codex", scope=RootScope.PROJECT)
    path = _write_skill(root)
    repository, reconciler = _reconciler(tmp_path)
    reconciler.reconcile([root])
    path.write_text("---\nname: Example\ndescription: changed\n---\nBody\n", encoding="utf-8")
    monkeypatch.chdir(project)

    summary = reconciler.reconcile([root], changed_paths=[Path(".codex/skills/example/SKILL.md")])

    assert summary.updated == 1
    assert repository.list_current_skills()[0].description == "changed"


def test_reconcile_cwd_relative_deleted_path_marks_skill_missing(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    root_path = project / ".codex" / "skills"
    root_path.mkdir(parents=True)
    root = LibraryRoot(root_id="root-1", path=root_path, provider="codex", scope=RootScope.PROJECT)
    path = _write_skill(root)
    repository, reconciler = _reconciler(tmp_path)
    reconciler.reconcile([root])
    path.unlink()
    path.parent.rmdir()
    monkeypatch.chdir(project)

    summary = reconciler.reconcile([root], changed_paths=[Path(".codex/skills/example/SKILL.md")])

    assert summary.removed == 1
    current = repository.get_current_skill(skill_id("codex", "project", "example/SKILL.md"))
    assert current is not None
    assert current.status is SkillStatus.MISSING


def test_reconcile_embeds_each_new_snapshot_but_not_restoration(tmp_path: Path) -> None:
    class Embedding:
        model_id = "test-v1"

        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def encode(self, texts: list[str]) -> list[list[float]]:
            self.calls.append(texts)
            return [[0.5] for _ in texts]

    root = _root(tmp_path)
    path = _write_skill(root)
    repository, _ = _reconciler(tmp_path)
    embedding = Embedding()
    reconciler = CatalogReconciler(repository, embedding=embedding)

    reconciler.reconcile([root])
    path.write_text("---\nname: Example\ndescription: changed\n---\nNew body\n", encoding="utf-8")
    reconciler.reconcile([root])
    restored_content = path.read_text(encoding="utf-8")
    path.unlink()
    path.parent.rmdir()
    reconciler.reconcile([root])
    path.parent.mkdir()
    path.write_text(restored_content, encoding="utf-8")
    reconciler.reconcile([root])

    assert len(embedding.calls) == 2
    assert len(repository.get_vectors("test-v1")) == 2


def test_reconcile_skips_parse_and_hash_for_unchanged_fingerprint(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    _write_skill(root)
    _, reconciler = _reconciler(tmp_path)
    from skillcheck.catalog import reconcile as reconcile_module

    original_parse = reconcile_module.parse_skill
    calls = 0

    def counting_parse(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_parse(*args, **kwargs)

    monkeypatch.setattr(reconcile_module, "parse_skill", counting_parse)

    reconciler.reconcile([root])
    reconciler.reconcile([root])

    assert calls == 1
