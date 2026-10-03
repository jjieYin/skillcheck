from __future__ import annotations

from skillcheck.core.parser import parse_skill
from tests.helpers_fingerprints import fixture_root, load_pair


def test_fingerprint_fixtures_are_repository_portable() -> None:
    for name in (
        "exact-copy",
        "metadata-only",
        "format-only",
        "asset-only",
        "script-only",
        "polarity",
        "full-lite",
        "unrelated",
        "shared-boilerplate",
    ):
        left, right = load_pair(name)
        assert (left / "SKILL.md").is_file()
        assert (right / "SKILL.md").is_file()
    assert (fixture_root("cjk") / "SKILL.md").is_file()
    assert (fixture_root("mixed-language") / "SKILL.md").is_file()


def test_metadata_only_fixture_expects_behavior_identity() -> None:
    first, second = load_pair("metadata-only")
    left = parse_skill(first)
    right = parse_skill(second)

    assert left.behavior_hash == right.behavior_hash
    assert left.content_hash != right.content_hash
