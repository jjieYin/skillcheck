from types import SimpleNamespace

import pytest


class FakePipeline:
    def __init__(self) -> None:
        self.last_review = None
        self.config = SimpleNamespace(
            effective_review_mode=lambda *, interactive, cli_value: cli_value or "none"
        )

    def run(self, scope, review):
        self.last_review = review.value
        return SimpleNamespace(
            skill_count=0,
            report=SimpleNamespace(markdown="report.md", json_path="report.json"),
        )


@pytest.fixture
def fake_pipeline() -> FakePipeline:
    return FakePipeline()
