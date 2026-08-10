from pathlib import Path

import pytest

from skillcheck.targets.codex import CodexTarget
from skillcheck.targets.config_io import ConfigFormatError


def test_codex_install_is_idempotent_and_uninstall_preserves_other(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    original = '[mcp_servers.other]\ncommand = "other"\n'
    config.write_text(original, encoding="utf-8")
    target = CodexTarget(config)

    first = target.install(target.preview("global"))
    second = target.install(target.preview("global"))
    assert first.changed is True
    assert second.changed is False
    assert "skillcheck" in config.read_text(encoding="utf-8")
    assert 'command = "other"' in config.read_text(encoding="utf-8")

    removed = target.uninstall("global")
    restored = config.read_text(encoding="utf-8")
    assert removed.changed is True
    assert "skillcheck" not in restored
    assert 'command = "other"' in restored


def test_codex_refuses_overwrite_after_preview_conflict(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[other]\nvalue = 1\n", encoding="utf-8")
    target = CodexTarget(config)
    change = target.preview("global")
    config.write_text("[other]\nvalue = 2\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="发生变化"):
        target.install(change)


def test_codex_does_not_write_malformed_toml(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[broken\n", encoding="utf-8")
    with pytest.raises(ConfigFormatError, match="未写入"):
        CodexTarget(config).preview("global")
    assert "skillcheck" not in config.read_text(encoding="utf-8")

