"""Release manifest validation used by the Windows installer."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from skillcheck.models.installation import ReleaseManifest


def verify_asset(path: Path | str, manifest: ReleaseManifest) -> None:
    asset = Path(path)
    if not asset.is_file():
        raise ValueError(f"发布文件不存在：{asset}")
    digest = sha256(asset.read_bytes()).hexdigest()
    if digest.casefold() != manifest.sha256.casefold():
        raise ValueError(f"SHA-256 校验失败：{asset.name}")


def load_manifest(path: Path | str) -> ReleaseManifest:
    import json

    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        return ReleaseManifest.model_validate(payload)
    except Exception as exc:
        raise ValueError(f"发布 Manifest 无效：{manifest_path}") from exc

