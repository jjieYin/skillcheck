from __future__ import annotations

from types import SimpleNamespace

from skillcheck.pipelines.review_pipeline import ReviewPipeline
from skillcheck.reviewers.packet import ReviewPacket


class FailingAdapter:
    def detect(self):
        return SimpleNamespace(available=True, reason=None)

    def review(self, packet):
        return SimpleNamespace(returncode=1, timed_out=False, stdout="", stderr="failed")


def test_review_failure_preserves_base_groups() -> None:
    groups = [{"group_id": "g1", "relation": "HIGH_OVERLAP"}]
    pipeline = ReviewPipeline(
        {"codex": FailingAdapter()},
        repositories=SimpleNamespace(reviews=__import__("skillcheck.pipelines.review_pipeline", fromlist=["ReviewRepository"]).ReviewRepository()),
        packet_builder=lambda groups: [ReviewPacket(packet_id="p1", groups=groups)],
    )
    result = pipeline.review("run-1", groups, "codex")
    assert result.status.value == "failed"
    assert "Codex 复核未完成" in result.error
    assert groups == [{"group_id": "g1", "relation": "HIGH_OVERLAP"}]


def test_none_review_does_not_start_adapter() -> None:
    pipeline = ReviewPipeline({"codex": FailingAdapter()})
    result = pipeline.review("run-1", [], "none")
    assert result.status.value == "skipped"

