import json
from pathlib import Path

from skillcheck.targets.claude import ClaudeTarget


def test_claude_preserves_unknown_json_fields_and_is_idempotent(tmp_path: Path) -> None:
    config = tmp_path / "claude.json"
    config.write_text(
        json.dumps(
            {
                "theme": "dark",
                "mcpServers": {"other": {"command": "other", "args": []}},
            }
        ),
        encoding="utf-8",
    )
    target = ClaudeTarget(config)
    first = target.install(target.preview("global"))
    second = target.install(target.preview("global"))
    payload = json.loads(config.read_text(encoding="utf-8"))
    assert first.changed is True
    assert second.changed is False
    assert payload["theme"] == "dark"
    assert payload["mcpServers"]["other"]["command"] == "other"
    assert payload["mcpServers"]["skillcheck"]["args"] == ["serve", "--mcp"]

    target.uninstall("global")
    payload = json.loads(config.read_text(encoding="utf-8"))
    assert "skillcheck" not in payload["mcpServers"]
    assert "other" in payload["mcpServers"]

