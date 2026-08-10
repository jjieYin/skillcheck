from pathlib import Path

import yaml

from skillcheck.config.loader import load_or_create_config


def test_v1_config_is_backed_up_and_migrated(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump({"extra_paths": ["D:/skills"], "llm": {"enabled": True}}),
        encoding="utf-8",
    )
    config = load_or_create_config(path, home=tmp_path)
    assert config.schema_version == 2
    assert config.scan.extra_paths == [Path("D:/skills")]
    assert config.review.mode == "ask"
    assert config.review.direct_api_compat is False
    assert config.llm.enabled is False
    assert path.with_suffix(".yaml.v1.bak").exists()


def test_noninteractive_review_defaults_to_none(tmp_path) -> None:
    config = load_or_create_config(tmp_path / "config.yaml", home=tmp_path)
    assert config.effective_review_mode(interactive=False, cli_value=None) == "none"
