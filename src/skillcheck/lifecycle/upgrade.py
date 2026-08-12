"""Verified upgrade and rollback orchestration."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from skillcheck.lifecycle.release_manifest import verify_asset


class UpgradeResult(BaseModel):
    changed: bool
    current_version: str | None = None
    message: str = ""


@dataclass(frozen=True)
class VersionInstall:
    version: str
    path: Path


@dataclass(frozen=True)
class SmokeResult:
    ok: bool
    message: str = ""


class LocalUpgradeLayout:
    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "skillcheck"))
        self.versions = self.root / "versions"
        self.current_marker = self.root / "current.txt"
        self.previous_marker = self.root / "previous.txt"

    def current(self) -> VersionInstall | None:
        return self._read_marker(self.current_marker)

    def previous_verified(self) -> VersionInstall | None:
        return self._read_marker(self.previous_marker)

    def stage_release(self, release):
        return release

    def unpack_candidate(self, release) -> VersionInstall:
        self.versions.mkdir(parents=True, exist_ok=True)
        path = self.versions / f".candidate-{release.version}-{uuid.uuid4().hex}"
        path.mkdir(parents=True, exist_ok=False)
        with zipfile.ZipFile(release.asset) as archive:
            archive.extractall(path)
        return VersionInstall(release.version, path)

    def remove_candidate(self, candidate: VersionInstall) -> None:
        if candidate.path.exists() and candidate.path.name.startswith(".candidate-"):
            shutil.rmtree(candidate.path, ignore_errors=True)

    def _read_marker(self, marker: Path) -> VersionInstall | None:
        if not marker.is_file():
            return None
        version = marker.read_text(encoding="utf-8").strip()
        path = self.versions / version
        return VersionInstall(version, path) if version and path.exists() else None


class LocalVerifier:
    def verify(self, asset: Path, manifest) -> None:
        verify_asset(asset, manifest)

    def smoke(self, install: VersionInstall) -> SmokeResult:
        executable = install.path / "skillcheck.exe"
        if not executable.exists():
            return SmokeResult(False, "候选版本缺少 skillcheck.exe")
        try:
            version = subprocess.run([str(executable), "version"], capture_output=True, text=True, check=False)
            doctor = subprocess.run([str(executable), "doctor", "--json"], capture_output=True, text=True, check=False)
        except OSError as exc:
            return SmokeResult(False, f"候选版本无法启动：{type(exc).__name__}")
        if version.returncode != 0:
            return SmokeResult(False, "候选版本冒烟检查失败")
        if doctor.returncode > 1:
            return SmokeResult(True, "候选版本可启动；现有 Skillcheck 状态需要后续诊断")
        return SmokeResult(True, "候选版本自检通过")


class LocalSwitcher:
    def __init__(self, layout: LocalUpgradeLayout) -> None:
        self.layout = layout

    def activate(self, candidate: VersionInstall, previous: VersionInstall | None = None) -> UpgradeResult:
        final = self.layout.versions / candidate.version
        if candidate.path != final:
            if final.exists():
                shutil.rmtree(final)
            candidate.path.replace(final)
            candidate = VersionInstall(candidate.version, final)
        current = self.layout.current()
        if current is not None and current.version != candidate.version:
            self.layout.previous_marker.write_text(current.version, encoding="utf-8")
        self.layout.root.mkdir(parents=True, exist_ok=True)
        self.layout.current_marker.write_text(candidate.version, encoding="utf-8")
        bin_dir = self.layout.root / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        shim = bin_dir / "skillcheck.cmd"
        executable = candidate.path / "skillcheck.exe"
        shim.write_text(f"@echo off\r\n\"{executable}\" %*\r\n", encoding="ascii")
        return UpgradeResult(changed=True, current_version=candidate.version, message="升级已切换")


class LocalResults:
    def failed(self, message: str) -> UpgradeResult:
        return UpgradeResult(changed=False, message=message)

    def developer_install(self, command: str) -> UpgradeResult:
        return UpgradeResult(changed=False, message=f"开发安装请执行：{command}")


class LocalUpgradeContext:
    def __init__(self, root: Path | str | None = None) -> None:
        self.layout = LocalUpgradeLayout(root)
        self.release_client = None
        self.verifier = LocalVerifier()
        self.switcher = LocalSwitcher(self.layout)
        self.results = LocalResults()

    def installation_kind(self) -> str:
        return "portable" if getattr(sys, "frozen", False) else "pip"


class UpgradeManager:
    def __init__(self, context) -> None:
        self.context = context

    def install(self, version: str):
        if self.context.installation_kind() == "pip":
            result_factory = getattr(self.context, "results", None)
            if result_factory is not None and hasattr(result_factory, "developer_install"):
                return result_factory.developer_install("python -m pip install --upgrade skillcheck")
            return UpgradeResult(
                changed=False,
                current_version=self._current_version(),
                message="pip 安装请由开发者环境执行升级命令",
            )
        release = self.context.release_client.fetch(version)
        candidate = self.context.layout.stage_release(release)
        self.context.verifier.verify(candidate.asset, release.manifest)
        unpacked = self.context.layout.unpack_candidate(candidate)
        smoke = self.context.verifier.smoke(unpacked)
        if not smoke.ok:
            self.context.layout.remove_candidate(unpacked)
            return self._failed(smoke.message)
        return self.context.switcher.activate(unpacked, previous=self.context.layout.current())

    def rollback(self):
        previous = self.context.layout.previous_verified()
        if previous is None:
            raise RuntimeError("没有可回滚的已验证版本")
        return self.context.switcher.activate(previous, previous=self.context.layout.current())

    def _current_version(self) -> str | None:
        current = self.context.layout.current()
        return getattr(current, "version", None) if current is not None else None

    def _failed(self, message: str):
        result_factory = getattr(self.context, "results", None)
        if result_factory is not None and hasattr(result_factory, "failed"):
            return result_factory.failed(message)
        return UpgradeResult(changed=False, current_version=self._current_version(), message=message)
