"""Build a native one-folder executable and release metadata."""

from __future__ import annotations

import argparse
import platform as host_platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from scripts.render_manifest import render
except ImportError:  # direct ``python scripts/build_release.py`` execution
    from render_manifest import render


@dataclass(frozen=True)
class ReleaseTarget:
    platform: str
    arch: str

    @property
    def suffix(self) -> str:
        return ".zip" if self.platform == "windows" else ".tar.gz"

    def asset_name(self, version: str) -> str:
        return f"skillcheck-{version}-{self.platform}-{self.arch}{self.suffix}"


def release_matrix() -> list[ReleaseTarget]:
    return [
        ReleaseTarget("windows", "x64"),
        ReleaseTarget("linux", "x64"),
        ReleaseTarget("macos", "x64"),
        ReleaseTarget("macos", "arm64"),
    ]


def native_target() -> tuple[str, str]:
    platform_name = {
        "Windows": "windows",
        "Linux": "linux",
        "Darwin": "macos",
    }.get(host_platform.system())
    architecture = {
        "amd64": "x64",
        "x86_64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(host_platform.machine().casefold())
    if platform_name is None or architecture is None:
        raise SystemExit(
            f"不支持的构建环境：{host_platform.system()} {host_platform.machine()}"
        )
    return platform_name, architecture


def build(version: str, platform: str, arch: str) -> Path:
    target = ReleaseTarget(platform.casefold(), arch.casefold())
    if target not in release_matrix():
        raise SystemExit(f"不支持的发布目标：{target.platform} {target.arch}")
    if native_target() != (target.platform, target.arch):
        raise SystemExit(
            "PyInstaller 必须在目标平台原生构建："
            f"当前 {native_target()[0]} {native_target()[1]}，"
            f"目标 {target.platform} {target.arch}"
        )

    root = Path(__file__).resolve().parents[1]
    dist = root / "dist" / f"skillcheck-{version}-{platform}-{arch}"
    generated = root / "dist" / "skillcheck"
    work = root / "build" / f"pyinstaller-{platform}-{arch}"
    dist.parent.mkdir(parents=True, exist_ok=True)
    if generated.exists():
        shutil.rmtree(generated)
    if work.exists():
        shutil.rmtree(work)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(root / "dist"),
        "--workpath",
        str(work),
        str(root / "skillcheck.spec"),
    ]
    subprocess.run(command, cwd=root, check=True)
    if not generated.exists():
        raise SystemExit(f"PyInstaller 未生成目录：{generated}")
    if dist.exists():
        shutil.rmtree(dist)
    generated.rename(dist)

    executable_name = "skillcheck.exe" if target.platform == "windows" else "skillcheck"
    if not (dist / executable_name).is_file():
        raise SystemExit(f"发布目录缺少可执行文件：{dist / executable_name}")

    asset = root / "dist" / target.asset_name(version)
    if target.suffix == ".zip":
        shutil.make_archive(str(asset.with_suffix("")), "zip", root_dir=dist)
    else:
        shutil.make_archive(str(asset.with_suffix("").with_suffix("")), "gztar", root_dir=dist)
    release_dir = root / "dist" / "release" / f"{target.platform}-{target.arch}"
    if release_dir.exists():
        shutil.rmtree(release_dir)
    render(
        asset,
        version=version,
        output=release_dir,
        platform=platform,
        architecture=arch,
    )
    return asset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--platform", default="windows")
    parser.add_argument("--arch", default="x64")
    args = parser.parse_args()
    print(build(args.version, args.platform, args.arch))


if __name__ == "__main__":
    main()
