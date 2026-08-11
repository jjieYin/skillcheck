from pathlib import Path

FORBIDDEN = (
    "skillcheck.reviewers",
    "ReviewMode",
    "--review",
    "CodexReviewAdapter",
    "ClaudeReviewAdapter",
    "LLMConfig",
)


def test_source_tree_contains_no_legacy_review_architecture():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/skillcheck").rglob("*.py")
    )
    for token in FORBIDDEN:
        assert token not in source
