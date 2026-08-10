from __future__ import annotations

import hashlib
import os
from pathlib import Path


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def root_id(provider: str, scope: str, path: Path | str) -> str:
    normalized = os.path.normcase(str(Path(path).expanduser().resolve()))
    return f"root-{_digest(f'{provider}|{scope}|{normalized}')}"


def skill_id(provider: str, scope: str, relative_path: Path | str) -> str:
    relative = Path(relative_path).as_posix().strip("/").casefold()
    return f"skill-{_digest(f'{provider}|{scope}|{relative}')}"


def snapshot_id(identity: str, content_hash: str) -> str:
    return f"snapshot-{_digest(f'{identity}|{content_hash}')}"
