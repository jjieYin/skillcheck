from __future__ import annotations

import shutil
from pathlib import Path


class InstallationRollback:
    def remove_created(self, paths: list[Path]) -> None:
        for path in paths:
            if path.exists() and path.is_dir():
                shutil.rmtree(path)
