from pathlib import Path

import pytest

from skillcheck.installer import InstallBlocked, _validate_target_root


def test_install_rejects_home_and_workspace_roots() -> None:
    with pytest.raises(InstallBlocked, match="过宽"):
        _validate_target_root(Path.home())
    with pytest.raises(InstallBlocked, match="过宽"):
        _validate_target_root(Path.cwd())

