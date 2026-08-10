from skillcheck.config import AppConfig, load_or_create_config, yaml_payload


def test_new_config_has_v4_sections_and_no_secret(tmp_path) -> None:
    config = load_or_create_config(tmp_path / "config.yaml", home=tmp_path)
    payload = yaml_payload(config)
    assert payload["schema_version"] == 4
    assert {"scan", "review", "targets", "reports", "privacy", "catalog"} <= payload.keys()
    assert "sk-live-example" not in str(payload)


def test_extra_paths_property_proxies_to_nested_scan_config(tmp_path) -> None:
    config = AppConfig.default(tmp_path)
    config.extra_paths = [tmp_path / "custom skills"]
    assert config.scan.extra_paths == [tmp_path / "custom skills"]
