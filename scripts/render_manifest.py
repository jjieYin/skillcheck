"""Render a release manifest and SHA256SUMS for an asset."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def render(asset: Path, *, version: str, output: Path, platform: str, architecture: str) -> None:
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    manifest = {
        "version": version,
        "platform": platform,
        "architecture": architecture,
        "asset_name": asset.name,
        "sha256": digest,
        "data_schema_version": 5,
        "minimum_compatible_version": "0.5.0",
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "SHA256SUMS").write_text(f"{digest}  {asset.name}\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("asset", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, default=Path("release"))
    parser.add_argument("--platform", default="windows")
    parser.add_argument("--arch", default="x64")
    args = parser.parse_args()
    render(
        args.asset,
        version=args.version,
        output=args.output,
        platform=args.platform,
        architecture=args.arch,
    )


if __name__ == "__main__":
    main()
