from skillcheck.models.review import ReviewStatus
from skillcheck.pipelines.scan_pipeline import ReviewMode, ScanPipeline, ScanScope


def test_scan_pipeline_writes_base_report_without_agent(fake_context, skill_library) -> None:
    outcome = ScanPipeline(fake_context).run(
        ScanScope(paths=[str(skill_library)]),
        ReviewMode.NONE,
    )
    assert outcome.skill_count == 2
    assert outcome.report.markdown.exists()
    assert outcome.report.json_path.exists()
    assert outcome.review.status is ReviewStatus.SKIPPED
    assert outcome.modified_skill_paths == []
