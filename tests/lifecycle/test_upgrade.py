from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from skillcheck.lifecycle.upgrade import LocalVerifier, UpgradeManager, VersionInstall


class UpgradeContext:
    def __init__(self, tmp_path: Path, *, invalid_hash=False, failed_smoke=False) -> None:
        self.invalid_hash = invalid_hash
        self.failed_smoke = failed_smoke
        self.current_version_record = SimpleNamespace(version="0.3.0-beta")
        self.previous = SimpleNamespace(version="0.2.0-alpha")
        self.removed = False
        self.layout = self
        self.release_client = self
        self.verifier = self
        self.switcher = self
        self.results = self

    def installation_kind(self): return "portable"
    def fetch(self, version): return SimpleNamespace(asset=Path("asset.zip"), manifest=object(), version=version)
    def stage_release(self, release): return release
    def verify(self, asset, manifest):
        if self.invalid_hash: raise ValueError("SHA-256 校验失败")
    def unpack_candidate(self, candidate): return SimpleNamespace(version="0.4.0-beta")
    def smoke(self, candidate): return SimpleNamespace(ok=not self.failed_smoke, message="冒烟失败")
    def remove_candidate(self, candidate): self.removed = True
    def current(self): return self.current_version_record
    def previous_verified(self): return self.previous
    def activate(self, candidate, previous=None): return SimpleNamespace(changed=True, current_version=candidate.version)
    def failed(self, message): return SimpleNamespace(changed=False, message=message)


def test_hash_failure_keeps_current_version(tmp_path: Path) -> None:
    context = UpgradeContext(tmp_path, invalid_hash=True)
    with pytest.raises(ValueError, match="SHA-256"):
        UpgradeManager(context).install("0.4.0-beta")
    assert context.current_version_record.version == "0.3.0-beta"


def test_smoke_failure_keeps_current_and_removes_candidate(tmp_path: Path) -> None:
    context = UpgradeContext(tmp_path, failed_smoke=True)
    result = UpgradeManager(context).install("0.4.0-beta")
    assert result.changed is False
    assert context.current_version_record.version == "0.3.0-beta"
    assert context.removed is True


def test_rollback_switches_to_previous_verified_version(tmp_path: Path) -> None:
    result = UpgradeManager(UpgradeContext(tmp_path)).rollback()
    assert result.current_version == "0.2.0-alpha"


def test_candidate_smoke_does_not_block_on_existing_state_diagnostics(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "skillcheck.exe"
    executable.touch()
    results = iter([
        SimpleNamespace(returncode=0),
        SimpleNamespace(returncode=2),
    ])

    monkeypatch.setattr(
        "skillcheck.lifecycle.upgrade.subprocess.run",
        lambda *args, **kwargs: next(results),
    )

    result = LocalVerifier().smoke(VersionInstall("0.5.1", tmp_path))

    assert result.ok is True
    assert "后续诊断" in result.message
