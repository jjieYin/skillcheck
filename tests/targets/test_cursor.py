import json
from pathlib import Path

import pytest

from skillcheck.targets.config_io import ConfigFormatError
from skillcheck.targets.cursor import CursorTarget


def test_cursor_creates_missing_json_config(tmp_path: Path) -> None:
    config = tmp_path / "mcp.json"
    target = CursorTarget(config)
    result = target.install(target.preview("global"))
    payload = json.loads(config.read_text(encoding="utf-8"))
    assert result.changed is True
    assert payload["mcpServers"]["skillcheck"]["command"] == "skillcheck"
    assert target.validate("global") is True


def test_cursor_does_not_overwrite_malformed_json(tmp_path: Path) -> None:
    config = tmp_path / "mcp.json"
    config.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ConfigFormatError, match="未写入"):
        CursorTarget(config).preview("global")

