from __future__ import annotations

from tests.helpers_fingerprints import load_pair


def test_vectorization_regression_pairs_are_available_without_user_paths() -> None:
    for name in ("exact-copy", "full-lite", "polarity", "shared-boilerplate", "unrelated"):
        left, right = load_pair(name)
        assert (left / "SKILL.md").is_file()
        assert (right / "SKILL.md").is_file()
