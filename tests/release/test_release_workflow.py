from pathlib import Path

WORKFLOW = Path(".github/workflows/release.yml").read_text(encoding="utf-8")


def test_release_workflow_builds_native_assets_before_uploading() -> None:
    assert "matrix:" in WORKFLOW
    assert "scripts/build_release.py" in WORKFLOW
    assert "actions/upload-artifact@v4" in WORKFLOW
    assert "actions/download-artifact@v4" in WORKFLOW
    assert "softprops/action-gh-release@v2" in WORKFLOW


def test_release_workflow_never_uses_readme_as_release_asset() -> None:
    assert "render_manifest.py README.md" not in WORKFLOW
    assert "README.md" not in WORKFLOW


def test_release_workflow_validates_manifest_hashes_before_publish() -> None:
    assert "sha256sum" in WORKFLOW
    assert "asset_name" in WORKFLOW
    assert "fail_on_unmatched_files: true" in WORKFLOW


def test_release_workflow_rejects_version_mismatched_binary() -> None:
    assert 'version_output="$($executable version)"' in WORKFLOW
    assert 'grep -F "skillcheck ${version}"' in WORKFLOW
    assert "release version mismatch" in WORKFLOW
