from pathlib import Path

from skillcheck.config import AppConfig, load_or_create_config


def test_default_config_uses_personal_skill_paths(tmp_path: Path) -> None:
    config = AppConfig.default(home=tmp_path)
    assert tmp_path / ".codex" / "skills" in config.scan_paths
    assert tmp_path / ".agents" / "skills" in config.scan_paths
    assert tmp_path / ".claude" / "skills" in config.scan_paths
    assert config.llm.api_key is None


def test_api_key_is_read_from_environment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "secret")
    path = tmp_path / "config.yaml"
    path.write_text("llm:\n  api_key_env: TEST_LLM_KEY\n", encoding="utf-8")
    config = load_or_create_config(path, home=tmp_path)
    assert config.llm.api_key == "secret"
    assert "secret" not in path.read_text(encoding="utf-8")
