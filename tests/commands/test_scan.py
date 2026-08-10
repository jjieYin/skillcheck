from typer.testing import CliRunner

from skillcheck.app.main import app

runner = CliRunner()


def test_scan_defaults_to_no_review_in_noninteractive_mode(fake_pipeline, monkeypatch) -> None:
    monkeypatch.setattr("skillcheck.commands.scan.build_scan_pipeline", lambda _: fake_pipeline)
    result = runner.invoke(app, ["scan", "--no-interactive"])
    assert result.exit_code == 0
    assert fake_pipeline.last_review == "none"
