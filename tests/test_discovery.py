from pathlib import Path

from skillcheck.config import AppConfig
from skillcheck.discovery import discover_skills
from tests.helpers import write_skill


def test_discover_groups_same_content_across_providers(tmp_path: Path) -> None:
    codex = tmp_path / ".codex/skills/api-check"
    agents = tmp_path / ".agents/skills/api-check-copy"
    write_skill(codex, name="api-check", body="same")
    write_skill(agents, name="api-check-copy", body="same")
    result = discover_skills(AppConfig.default(tmp_path), cwd=tmp_path)
    assert len(result.unique_skills) == 2
    assert len(result.hash_duplicate_groups) == 1
    assert {skill.provider.value for skill in result.hash_duplicate_groups[0]} == {"codex", "agents"}


def test_discover_deduplicates_overlapping_scan_roots(tmp_path: Path) -> None:
    root = tmp_path / "custom"
    skill = write_skill(root / "demo")
    config = AppConfig.default(tmp_path)
    config.scan_paths = [root, root / "demo"]
    result = discover_skills(config, cwd=tmp_path)
    assert [item.root_path for item in result.unique_skills] == [skill.resolve()]


def test_discover_keeps_missing_path_as_nonfatal(tmp_path: Path) -> None:
    config = AppConfig.default(tmp_path)
    config.scan_paths = [tmp_path / "missing"]
    result = discover_skills(config, cwd=tmp_path)
    assert result.unique_skills == []
    assert result.errors == []
