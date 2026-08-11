from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from skillcheck.app.main import app
from skillcheck.catalog.database import CatalogDatabase
from skillcheck.config import load_config
from skillcheck.lifecycle.doctor import CheckStatus, DoctorCheck, DoctorReport

runner = CliRunner()


class FakeDoctor:
    def __init__(self, context) -> None:
        self.context = context

    def run(self, *, fix=False):
        return DoctorReport(
            checks=[
                DoctorCheck(
                    code="runtime.version",
                    status=CheckStatus.WARNING,
                    message="假 Token 不应显示",
                    remediation="升级",
                )
            ]
        )

    def plan(self, report):
        return SimpleNamespace(actions=[])


def test_doctor_json_does_not_print_sensitive_values(monkeypatch) -> None:
    monkeypatch.setattr("skillcheck.commands.doctor.Doctor", FakeDoctor)
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1
    assert "假 Token" not in result.stdout
    assert "runtime.version" in result.stdout


def test_doctor_fix_initializes_a_real_catalog_only_after_confirmation(monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state"
    config_path = state / "config.yaml"
    monkeypatch.setenv("SKILLCHECK_HOME", str(state))
    pipeline = SimpleNamespace(
        registry=SimpleNamespace(detect_all=list),
        discover=lambda: SimpleNamespace(agents=[]),
    )
    monkeypatch.setattr("skillcheck.commands.doctor._build_install_pipeline", lambda _config: pipeline)

    result = runner.invoke(app, ["doctor", "--fix", "--yes", "--config", str(config_path)])

    assert result.exit_code in {0, 1}
    config = load_config(config_path, create=False)
    assert config.catalog.initialized is True
    assert CatalogDatabase(config.catalog.database_path).schema_version() == 4
