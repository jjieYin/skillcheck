from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import pytest

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.governance import GovernanceAnalyzer
from skillcheck.sources import SourceSafetyError
from tests.helpers import write_skill


@pytest.fixture
def analyzer(tmp_path: Path) -> GovernanceAnalyzer:
    database = CatalogDatabase(tmp_path / "state" / "catalog.db")
    database.initialize()
    return GovernanceAnalyzer(
        CatalogRepository(database),
        staging_root=tmp_path / "state" / "staging",
    )


def test_source_analyze_binds_run_to_source_hash(analyzer: GovernanceAnalyzer, tmp_path: Path) -> None:
    source = write_skill(tmp_path / "source", name="incoming", body="Useful safe implementation details.")

    result = analyzer.analyze_source(str(source), scope="all", limit=20)
    stored = analyzer.repository.get_source_preflight(result.run_id)

    assert stored.run_id == result.run_id
    assert stored.source_hash.startswith("sha256:")
    assert stored.source == str(source)
    assert stored.expires_at > stored.created_at


def test_source_analyze_cleans_staging_after_failure(analyzer: GovernanceAnalyzer, tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr("../escape/SKILL.md", "unsafe")

    with pytest.raises(SourceSafetyError):
        analyzer.analyze_source(str(archive), scope="all", limit=20)

    assert list(analyzer.staging_root.iterdir()) == []


def test_source_preflight_records_deterministic_security_blockers(
    analyzer: GovernanceAnalyzer, tmp_path: Path
) -> None:
    source = write_skill(
        tmp_path / "unsafe",
        name="unsafe",
        body="The leaked value is sk-abcdefghijklmnop.",
    )

    result = analyzer.analyze_source(str(source), scope="all", limit=20)
    stored = analyzer.repository.get_source_preflight(result.run_id)

    assert any(item.rule_id.startswith("SEC") for item in stored.deterministic_blockers)


def test_source_preflight_does_not_block_on_an_existing_library_secret(
    analyzer: GovernanceAnalyzer, tmp_path: Path
) -> None:
    analyzer.catalog.upsert_root(
        LibraryRoot(root_id="catalog", path=tmp_path / "catalog", provider="codex", scope=RootScope.CUSTOM)
    )
    analyzer.catalog.upsert_snapshot(
        SkillSnapshot(
            snapshot_id="catalog-secret", skill_id="catalog-secret", root_id="catalog",
            relative_path="catalog-secret/SKILL.md", name="catalog-secret", description="existing",
            body="Existing old token: sk-abcdefghijklmnop.", content_hash="sha256:catalog-secret",
            indexed_at=datetime.now(UTC),
        )
    )
    source = write_skill(tmp_path / "safe", name="safe", body="A safe new implementation.")

    result = analyzer.analyze_source(str(source), scope="all", limit=20)

    assert analyzer.repository.get_source_preflight(result.run_id).deterministic_blockers == []
