from pathlib import Path

import pytest

from skillcheck.parser import SkillParseError, parse_skill


def test_parse_skill_extracts_frontmatter_and_hash() -> None:
    skill = parse_skill(Path("tests/fixtures/basic"))
    assert skill.name == "api-check"
    assert skill.tools == ["http-client"]
    assert skill.content_hash.startswith("sha256:")


def test_parse_skill_rejects_missing_skill_md(tmp_path: Path) -> None:
    with pytest.raises(SkillParseError, match="SKILL.md"):
        parse_skill(tmp_path)
