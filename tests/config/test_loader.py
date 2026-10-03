from __future__ import annotations

import pytest

from skillcheck.config import load_config, save_config


def test_missing_config_creates_only_v4_sections(tmp_path) -> None:
    path = tmp_path / "config.yaml"

    config = load_config(path, home=tmp_path)

    assert config.schema_version == 4
    assert set(config.model_dump()) == {
        "schema_version",
        "catalog",
        "targets",
        "reports",
        "privacy",
        "embedding",
        "security",
        "thresholds",
    }
    assert config.catalog.database_path == tmp_path / ".skillcheck" / "index.db"
    assert config.reports.directory == tmp_path / ".skillcheck" / "reports"
    assert config.targets.selection_initialized is False
    assert config.embedding.algorithm_revision == "2"


def test_agent_selection_is_persisted_exactly(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    config = load_config(path, home=tmp_path)
    config.targets.configured = ["codex", "cursor"]
    config.targets.selection_initialized = True
    save_config(path, config)

    loaded = load_config(path, home=tmp_path, create=False)
    assert loaded.targets.configured == ["codex", "cursor"]
    assert loaded.targets.selection_initialized is True


def test_old_config_version_is_rejected_without_rewriting_source(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    original = "schema_version: 3\ncatalog: {}\n"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version 4"):
        load_config(path, home=tmp_path)

    assert path.read_text(encoding="utf-8") == original


def test_legacy_fields_are_rejected(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("schema_version: 4\ncatalog: {}\nreview: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported fields"):
        load_config(path, home=tmp_path)


def test_unknown_nested_v4_field_is_rejected_without_rewriting_source(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    original = "schema_version: 4\ncatalog:\n  databasepath: unexpected\n"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="catalog.databasepath"):
        load_config(path, home=tmp_path)

    assert path.read_text(encoding="utf-8") == original
