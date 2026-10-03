from pathlib import Path

import pytest

from skillcheck.parser import SkillParseError, content_hash, instruction_hash, parse_skill


def test_parse_skill_extracts_frontmatter_and_hash() -> None:
    skill = parse_skill(Path("tests/fixtures/basic"))
    assert skill.name == "api-check"
    assert skill.tools == ["http-client"]
    assert skill.content_hash.startswith("sha256:")


def test_instruction_hash_ignores_assets_but_package_hash_does_not(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root in (first, second):
        root.mkdir()
        (root / "SKILL.md").write_text(
            "---\nname: demo\ndescription: same\n---\nBody\n", encoding="utf-8"
        )
    (first / "asset.txt").write_text("one", encoding="utf-8")
    (second / "asset.txt").write_text("two", encoding="utf-8")

    assert instruction_hash(first) == instruction_hash(second)
    assert content_hash(first) != content_hash(second)


def test_instruction_hash_is_stable_for_yaml_order_line_endings_and_trailing_space(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "SKILL.md").write_text(
        "---\nname: demo\ndescription: same\nmetadata:\n  z: 2\n  a: 1\n---\nBody   \n\n",
        encoding="utf-8",
    )
    (second / "SKILL.md").write_bytes(
        b"---\r\nmetadata:\r\n  a: 1\r\n  z: 2\r\ndescription: same\r\nname: demo\r\n---\r\nBody\r\n"
    )

    assert instruction_hash(first) == instruction_hash(second)


def test_instruction_hash_changes_for_meaningful_body_change(tmp_path: Path) -> None:
    root = tmp_path / "skill"
    root.mkdir()
    path = root / "SKILL.md"
    path.write_text("---\nname: demo\n---\nBody\n", encoding="utf-8")
    original = instruction_hash(root)
    path.write_text("---\nname: demo\n---\nDifferent body\n", encoding="utf-8")

    assert instruction_hash(root) != original


def test_v2_behavior_hash_ignores_metadata_and_package_hash_property_is_compatible(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root, author in ((first, "one"), (second, "two")):
        root.mkdir()
        (root / "SKILL.md").write_text(
            "---\n"
            "name: different-name\n"
            "description: same behavior\n"
            f"metadata:\n  author: {author}\n"
            "---\nCheck the response schema.\n",
            encoding="utf-8",
        )

    left = parse_skill(first)
    right = parse_skill(second)

    assert left.behavior_hash == right.behavior_hash
    assert left.package_hash == left.content_hash
    assert left.hash_algorithm_revision == "2"
    assert left.content_hash != right.content_hash


def test_v2_execution_hash_distinguishes_scripts_and_empty_sentinel(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    scripted = tmp_path / "scripted"
    for root in (empty, scripted):
        root.mkdir()
        (root / "SKILL.md").write_text("---\nname: demo\n---\nBody\n", encoding="utf-8")
    (scripted / "scripts").mkdir()
    (scripted / "scripts" / "run.py").write_text("print('one')\n", encoding="utf-8")

    empty_record = parse_skill(empty)
    scripted_record = parse_skill(scripted)

    assert empty_record.execution_hash == "sha256-v2:empty-scripts"
    assert scripted_record.execution_hash not in {None, empty_record.execution_hash}


@pytest.mark.parametrize("allowed_tools", ["http-client, fs-read", ["http-client", "fs-read"]])
def test_parse_skill_extracts_official_frontmatter_fields(tmp_path: Path, allowed_tools) -> None:
    (tmp_path / "SKILL.md").write_text(
        "---\n"
        "name: demo\n"
        "license: MIT\n"
        "compatibility: python>=3.11\n"
        "metadata:\n"
        "  owner: platform\n"
        f"allowed-tools: {allowed_tools!r}\n"
        "---\nBody\n",
        encoding="utf-8",
    )

    skill = parse_skill(tmp_path)

    assert skill.license == "MIT"
    assert skill.compatibility == "python>=3.11"
    assert skill.metadata == {"owner": "platform"}
    assert skill.allowed_tools == ["http-client", "fs-read"]


def test_parse_skill_rejects_missing_skill_md(tmp_path: Path) -> None:
    with pytest.raises(SkillParseError, match="SKILL.md"):
        parse_skill(tmp_path)


def test_parse_skill_reports_invalid_yaml_as_parse_error(tmp_path: Path) -> None:
    (tmp_path / "SKILL.md").write_text(
        "---\nname: demo\ndescription: `unquoted value\n---\nbody",
        encoding="utf-8",
    )
    with pytest.raises(SkillParseError, match="valid YAML"):
        parse_skill(tmp_path)
