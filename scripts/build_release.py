"""Build the Windows one-folder executable and release metadata."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from render_manifest import render


def build(version: str, platform: str, arch: str) -> Path:
    if platform.casefold() != "windows" or arch.casefold() != "x64":
        raise SystemExit("当前只支持 windows x64")
    root = Path(__file__).resolve().parents[1]
    dist = root / "dist" / f"skillcheck-{version}-{platform}-{arch}"
    work = root / "build" / "pyinstaller"
    dist.parent.mkdir(parents=True, exist_ok=True)
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
    generated = root / "dist" / "skillcheck"
    if generated != dist and generated.exists():
        if dist.exists():
            shutil.rmtree(dist)
        generated.rename(dist)
    asset = root / "dist" / f"skillcheck-{version}-{platform}-{arch}.zip"
    shutil.make_archive(str(asset.with_suffix("")), "zip", root_dir=dist)
    render(
        asset,
        version=version,
        output=root / "dist" / "release",
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
