from hashlib import sha256
from pathlib import Path

import pytest

from skillcheck.lifecycle.release_manifest import verify_asset
from skillcheck.models import ReleaseManifest


def test_release_asset_hash_must_match(tmp_path: Path) -> None:
    asset = tmp_path / "skillcheck.zip"
    asset.write_bytes(b"release")
    manifest = ReleaseManifest(
        version="0.5.1",
        platform="windows",
        architecture="x64",
        asset_name=asset.name,
        sha256=sha256(asset.read_bytes()).hexdigest(),
        data_schema_version=5,
        minimum_compatible_version="0.5.0",
    )
    assert manifest.data_schema_version == 5
    verify_asset(asset, manifest)
    asset.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        verify_asset(asset, manifest)
