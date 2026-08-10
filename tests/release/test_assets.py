from scripts.build_release import release_matrix


def test_release_matrix_covers_required_platforms() -> None:
    matrix = {(item.platform, item.arch) for item in release_matrix()}
    assert matrix == {
        ("windows", "x64"),
        ("windows", "arm64"),
        ("linux", "x64"),
        ("macos", "x64"),
        ("macos", "arm64"),
    }


def test_asset_names_are_stable() -> None:
    names = {item.asset_name("1.0.0") for item in release_matrix()}
    assert "skillcheck-1.0.0-windows-x64.zip" in names
    assert "skillcheck-1.0.0-macos-arm64.tar.gz" in names

