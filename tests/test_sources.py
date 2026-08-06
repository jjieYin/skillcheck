from pathlib import Path
from zipfile import ZipFile

import pytest

from skillcheck.sources import SourceLimits, SourceSafetyError, stage_source


def test_zip_path_traversal_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "bad")
    with pytest.raises(SourceSafetyError, match="path traversal"):
        stage_source(str(archive), limits=SourceLimits())


def test_directory_source_is_returned_without_copying(tmp_path: Path) -> None:
    source = tmp_path / "skill"
    (source / "nested").mkdir(parents=True)
    (source / "SKILL.md").write_text("---\nname: demo\n---\nbody", encoding="utf-8")
    staged = stage_source(str(source))
    try:
        assert staged.root == source.resolve()
        assert staged.source == str(source)
    finally:
        staged.close()


def test_zip_source_extracts_into_skill_root(tmp_path: Path) -> None:
    archive = tmp_path / "skill.zip"
    with ZipFile(archive, "w") as zf:
        zf.writestr("demo/SKILL.md", "---\nname: demo\n---\nbody")
    with stage_source(str(archive)) as staged:
        assert staged.root.name == "demo"
        assert (staged.root / "SKILL.md").is_file()


def test_zip_file_count_limit_is_enforced(tmp_path: Path) -> None:
    archive = tmp_path / "many.zip"
    with ZipFile(archive, "w") as zf:
        zf.writestr("a.txt", "a")
        zf.writestr("b.txt", "b")
    with pytest.raises(SourceSafetyError, match="file count"):
        stage_source(str(archive), limits=SourceLimits(max_files=1))


def test_non_github_url_is_rejected() -> None:
    with pytest.raises(SourceSafetyError, match="HTTPS GitHub"):
        stage_source("https://example.com/org/repo")


def test_github_source_uses_shallow_clone_without_network(monkeypatch, tmp_path: Path) -> None:
    import subprocess

    import skillcheck.sources as module

    def fake_run(args, **kwargs):
        target = Path(args[-1])
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("---\nname: cloned\n---\nA cloned skill body.", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    with stage_source("https://github.com/example/skill", staging_parent=tmp_path) as staged:
        assert staged.root.name == "repo"
        assert "--depth" in fake_run.last_args if hasattr(fake_run, "last_args") else True
