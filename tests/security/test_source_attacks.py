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
    import skillcheck.sources as sources

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

