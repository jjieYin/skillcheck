from pathlib import Path


def test_windows_installer_does_not_force_auto_yes() -> None:
    script = Path("install.ps1").read_text(encoding="utf-8")
    assert "install --target auto --yes" not in script
    assert "IsInputRedirected" in script
    assert "$doctorExitCode = $LASTEXITCODE" in script
    assert "环境诊断冒烟检查失败" not in script


def test_posix_installer_enters_wizard_only_on_tty() -> None:
    script = Path("install.sh").read_text(encoding="utf-8")
    assert "[ -t 0 ] && [ -t 1 ]" in script
    assert '"${BIN}/skillcheck" install' in script
