from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from skillcheck.app.main import app
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

