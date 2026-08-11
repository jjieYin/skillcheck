from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from skillcheck.app.main import app
from tests.helpers import write_skill

runner = CliRunner()


def test_add_preflights_then_installs_to_selected_target(monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state"
    library = tmp_path / "library"
    destination = tmp_path / "codex-skills"
    source = write_skill(tmp_path / "source", name="incoming", body="Useful safe implementation details.")
    write_skill(library / "existing", name="existing", body="Existing safe implementation details.")
    monkeypatch.setenv("SKILLCHECK_HOME", str(state))
    monkeypatch.setattr("skillcheck.commands.add._target_root", lambda _target, _config: destination)

    assert runner.invoke(app, ["init", str(library), "--yes"]).exit_code == 0
    result = runner.invoke(app, ["add", str(source), "--yes"])

    assert result.exit_code == 0
    assert "来源哈希" in result.stdout
    assert (destination / "incoming" / "SKILL.md").is_file()
