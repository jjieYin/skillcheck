from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from skillcheck.sources import SourceLimits, SourceSafetyError, stage_source


def test_absolute_zip_path_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "absolute.zip"
    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr("/escape.txt", "no")
    with pytest.raises(SourceSafetyError):
        stage_source(archive)


def test_zip_size_limit_rejects_bomb(tmp_path: Path) -> None:
    archive = tmp_path / "bomb.zip"
    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr("large.txt", "x" * 1024)
    with pytest.raises(SourceSafetyError, match="unpacked size"):
        stage_source(archive, limits=SourceLimits(max_unpacked_bytes=10))


def test_github_redirects_are_disabled(monkeypatch, tmp_path: Path) -> None:
    import subprocess

    from skillcheck import sources

    observed = {}

    def fake_run(args, **kwargs):
        observed["args"] = args
        target = Path(args[-1])
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("---\nname: demo\n---\nbody", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(sources, "subprocess", subprocess)
    monkeypatch.setattr(subprocess, "run", fake_run)
    with stage_source("https://github.com/example/skill", staging_parent=tmp_path):
        pass
    assert "http.followRedirects=false" in observed["args"]


def test_local_source_symlink_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text("---\nname: demo\n---\nbody", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = source / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(SourceSafetyError, match="symlink"):
        stage_source(source, staging_parent=tmp_path / "staging")

    staging = tmp_path / "staging"
    assert not staging.exists() or list(staging.iterdir()) == []
