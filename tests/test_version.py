import tomllib
from pathlib import Path

from skillcheck import __version__

EXPECTED_RELEASE_VERSION = "0.4.0"


def test_source_and_project_versions_match_v040_release() -> None:
    project = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert __version__ == EXPECTED_RELEASE_VERSION
    assert project["project"]["version"] == EXPECTED_RELEASE_VERSION
