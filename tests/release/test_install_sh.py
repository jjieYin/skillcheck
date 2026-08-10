from pathlib import Path


def test_posix_installer_is_data_preserving() -> None:
    script = Path("install.sh").read_text(encoding="utf-8")
    assert "XDG_DATA_HOME" in script
    assert "skillcheck" in script
    assert "rm -rf \"$TMP\"" in script
    assert "skills" not in script.lower() or "not" in script.lower()

