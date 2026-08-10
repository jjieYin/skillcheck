from pathlib import Path

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.config.models import AppConfig
from skillcheck.pipelines.init_pipeline import InitPipeline


def test_preview_is_side_effect_free_and_cancel_does_not_create_catalog(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    root = home / ".codex" / "skills"
    root.mkdir(parents=True)
    config_path = tmp_path / "config.yaml"
    config = AppConfig.default(home)
    pipeline = InitPipeline(config, config_path, home=home, project=project)

    preview = pipeline.preview(pipeline.discover([]))
    result = pipeline.apply(preview, confirmed=False)

    assert [item.path for item in preview.roots] == [root.resolve()]
    assert preview.database_path == config.index_path
    assert result.changed is False
    assert not preview.database_path.exists()
    assert not config_path.exists()


def test_confirmed_apply_initializes_catalog_persists_roots_and_config(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    root = project / ".claude" / "skills"
    root.mkdir(parents=True)
    config_path = tmp_path / "config.yaml"
    config = AppConfig.default(home)
    pipeline = InitPipeline(config, config_path, home=home, project=project)

    result = pipeline.apply(pipeline.preview(pipeline.discover([])), confirmed=True)

    assert result.changed is True
    assert result.sync.revision == "initial"
    assert config.catalog.initialized is True
    assert config.catalog.roots == [root.resolve()]
    assert CatalogRepository(CatalogDatabase(config.index_path)).list_roots()[0].path == root.resolve()
    assert "schema_version: 4" in config_path.read_text(encoding="utf-8")
    assert "catalog:" in config_path.read_text(encoding="utf-8")
