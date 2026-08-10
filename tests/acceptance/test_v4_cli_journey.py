from __future__ import annotations

import json

from typer.testing import CliRunner

from skillcheck.app.main import app

runner = CliRunner()


def test_init_status_and_local_scan_form_the_cli_fallback_journey(monkeypatch, tmp_path) -> None:
    state = tmp_path / "state"
    library = tmp_path / "library"
    skill = library / "example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: example\ndescription: an example skill\n---\n\nUse this skill for examples.",
        encoding="utf-8",
    )
    monkeypatch.setenv("SKILLCHECK_HOME", str(state))

    initialized = runner.invoke(app, ["init", str(library), "--yes"])
    status = runner.invoke(app, ["status", "--json"])
    scan = runner.invoke(app, ["scan", "--json"])

    assert initialized.exit_code == 0
    assert status.exit_code == 0
    assert scan.exit_code == 0
    assert json.loads(status.stdout)["initialized"] is True
    payload = json.loads(scan.stdout)
    assert payload["skill_count"] >= 1
    assert payload["agent_reviews"] == []
