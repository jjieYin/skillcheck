"""Small GitHub release client with no install side effects."""

from __future__ import annotations

import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from skillcheck.lifecycle.release_manifest import load_manifest
from skillcheck.models import ReleaseManifest


@dataclass(frozen=True)
class ReleaseBundle:
    version: str
    asset: Path
    manifest: ReleaseManifest


class ReleaseClient:
    def __init__(self, repository: str = "jjieYin/skillcheck", *, cache_dir: Path | None = None) -> None:
        self.repository = repository
        self.cache_dir = cache_dir or Path(tempfile.gettempdir()) / "skillcheck-releases"

    def fetch(self, version: str) -> ReleaseBundle:
        normalized = version.lstrip("v")
        base = f"https://github.com/{self.repository}/releases/download/v{normalized}"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        asset_name = f"skillcheck-{normalized}-windows-x64.zip"
        asset = self.cache_dir / asset_name
        manifest_path = self.cache_dir / f"{normalized}-manifest.json"
        urllib.request.urlretrieve(f"{base}/{asset_name}", asset)
        urllib.request.urlretrieve(f"{base}/manifest.json", manifest_path)
        manifest = load_manifest(manifest_path)
        return ReleaseBundle(version=normalized, asset=asset, manifest=manifest)
