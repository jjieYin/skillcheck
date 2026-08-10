from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import skillcheck.app as app_package
from skillcheck.app.main import app
from skillcheck.config import load_or_create_config, save_config
from skillcheck.lifecycle.doctor import CheckStatus, Doctor
from skillcheck.lifecycle.uninstall import UninstallManager
from skillcheck.mcp.repositories import FileRepositories
from skillcheck.pipelines.review_pipeline import ReviewPipeline
from skillcheck.pipelines.setup_pipeline import SetupPipeline
from skillcheck.reviewers.registry import ReviewRegistry
from skillcheck.sources.archive import stage_archive
from skillcheck.sources.github import stage_github
from skillcheck.sources.legacy import SourceSafetyError
from skillcheck.sources.local import stage_directory
from skillcheck.sources.staging import ensure_within
from skillcheck.sources.staging import stage_source as stage_staging_source
from skillcheck.targets.base import AgentId
from skillcheck.targets.claude import ClaudeTarget
from skillcheck.targets.codex import CodexTarget
from skillcheck.targets.registry import TargetRegistry

runner = CliRunner()


def _skill(root: Path, name: str = "demo") -> Path:
    path = root / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: demo\n---\nA local skill body.",
        encoding="utf-8",
    )
    return path


def _isolated_config(tmp_path: Path, monkeypatch) -> Path:
    config = tmp_path / ".skillcheck" / "config.yaml"
    monkeypatch.setenv("SKILLCHECK_HOME", str(config.parent))
    loaded = load_or_create_config(config, home=tmp_path)
    save_config(config, loaded)
    return config


def _report_paths(config: Path) -> tuple[Path, Path]:
    loaded = load_or_create_config(config)
    json_paths = sorted(loaded.reports_path.glob("*.json"))
    assert json_paths
    for json_path in reversed(json_paths):
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        if "run_id" in payload:
            return json_path.with_suffix(".md"), json_path
    raise AssertionError("没有找到 v2 扫描报告")


def test_first_run_scan_without_python_dependency(tmp_path: Path, monkeypatch) -> None:
    assert app_package.app is app
    source = tmp_path / "skills"
    _skill(source)
    config = _isolated_config(tmp_path, monkeypatch)
    result = runner.invoke(app, ["scan", str(source), "--no-interactive", "--config", str(config)])
    assert result.exit_code in {0, 1, 2}
    markdown, report_json = _report_paths(config)
    assert "报告" in result.output
    assert markdown.exists() and report_json.exists()


def test_agent_review_failure_does_not_lose_report(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "skills"
    _skill(source)
    config = _isolated_config(tmp_path, monkeypatch)
    # A missing registry entry is the deterministic equivalent of a failing
    # Codex process and keeps this acceptance test independent of local CLIs.
    monkeypatch.setattr(
        "skillcheck.app.context.build_review_pipeline",
        lambda _config: ReviewPipeline(ReviewRegistry()),
    )
    result = runner.invoke(
        app,
        ["scan", str(source), "--review", "codex", "--no-interactive", "--config", str(config)],
    )
    assert result.exit_code in {0, 1, 2}
    markdown, report_json = _report_paths(config)
    text = markdown.read_text(encoding="utf-8")
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    assert "## 确定性检查结论" in text
    assert "## Agent 语义复核" in text
    assert payload["agent_review"]["status"] == "failed"


def test_add_cancel_does_not_install(tmp_path: Path, monkeypatch) -> None:
    source = _skill(tmp_path / "incoming")
    config = _isolated_config(tmp_path, monkeypatch)
    loaded = load_or_create_config(config)
    target_root = tmp_path / ".codex" / "skills"
    loaded.scan_paths = [target_root]
    loaded.extra_paths = []
    save_config(config, loaded)
    result = runner.invoke(app, ["add", str(source), "--config", str(config)], input="n\n")
    assert result.exit_code == 0
    assert not (target_root / "demo").exists()
    assert "未安装" in result.output


def test_setup_then_uninstall_preserves_other_servers(tmp_path: Path) -> None:
    codex_path = tmp_path / "codex" / "config.toml"
    claude_path = tmp_path / "claude.json"
    codex_path.parent.mkdir(parents=True)
    codex_path.write_text('[mcp_servers.other-server]\ncommand = "other"\n', encoding="utf-8")
    claude_path.write_text(
        json.dumps({"mcpServers": {"other-server": {"command": "other"}}}),
        encoding="utf-8",
    )
    codex = CodexTarget(global_config=codex_path, launcher="skillcheck")
    claude = ClaudeTarget(global_config=claude_path, launcher="skillcheck")

    class Store:
        def record_targets(self, scope, results, validations) -> None:
            self.scope = scope
            self.results = results
            self.validations = validations

    registry = TargetRegistry({AgentId.CODEX: codex, AgentId.CLAUDE: claude})
    setup = SetupPipeline(registry, Store())
    preview = setup.preview(["codex", "claude"], scope="global")
    applied = setup.apply(preview, confirmed=True)
    assert applied.changed_files == [codex_path, claude_path]
    assert all(applied.validations)

    program = tmp_path / "program"
    program.mkdir()
    context = SimpleNamespace(
        layout=SimpleNamespace(
            owned_program_paths=lambda: [program / "skillcheck.exe"],
            owned_roots=lambda: [program],
        ),
        targets=SimpleNamespace(configured=lambda: [codex, claude]),
        agent_scope="global",
        helpers=SimpleNamespace(remove_program_after_exit=lambda _paths: None),
        data=SimpleNamespace(remove_selected=lambda _plan: None),
        results=SimpleNamespace(
            cancelled=lambda: SimpleNamespace(changed=False),
            completed=lambda _plan: SimpleNamespace(changed=True),
        ),
    )
    uninstall = UninstallManager(context)
    result = uninstall.execute(uninstall.plan(), confirmed=True)
    assert result.changed is True
    assert "other-server" in codex_path.read_text(encoding="utf-8")
    assert "other-server" in claude_path.read_text(encoding="utf-8")
    assert "skillcheck" not in codex_path.read_text(encoding="utf-8")
    assert "skillcheck" not in claude_path.read_text(encoding="utf-8")


def test_upgrade_failure_keeps_previous_binary(monkeypatch) -> None:
    class FailingContext:
        def __init__(self) -> None:
            self.current_version = "0.3.0-beta"
            self.removed = False
            self.layout = self
            self.release_client = self
            self.verifier = self
            self.switcher = self
            self.results = self

        def installation_kind(self):
            return "portable"

        def fetch(self, version):
            return SimpleNamespace(asset=Path("broken.zip"), manifest=object(), version=version)

        def stage_release(self, release):
            return release

        def verify(self, asset, manifest):
            return None

        def unpack_candidate(self, candidate):
            return SimpleNamespace(version=candidate.version)

        def smoke(self, candidate):
            return SimpleNamespace(ok=False, message="smoke failed")

        def remove_candidate(self, candidate):
            self.removed = True

        def current(self):
            return SimpleNamespace(version=self.current_version)

        def activate(self, candidate, previous=None):
            raise AssertionError("失败升级不应切换版本")

        def failed(self, message):
            return SimpleNamespace(changed=False, message=message)

    context = FailingContext()
    monkeypatch.setattr("skillcheck.commands.upgrade.build_upgrade_context", lambda: context)
    result = runner.invoke(app, ["upgrade", "broken-release"])
    assert result.exit_code == 1
    assert context.current().version == "0.3.0-beta"
    assert context.removed is True


def test_chinese_and_space_paths_work(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "中文 Skills 库"
    _skill(source, "带 空格")
    config = _isolated_config(tmp_path, monkeypatch)
    result = runner.invoke(app, ["scan", str(source), "--no-interactive", "--config", str(config)])
    assert result.exit_code in {0, 1, 2}
    _, report_json = _report_paths(config)
    assert json.loads(report_json.read_text(encoding="utf-8"))["skill_count"] == 1


def test_read_only_report_queries_and_doctor_repairs(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    payload = {
        "report_id": "R-1",
        "skill_count": 2,
        "installation_count": 2,
        "groups": [
            {
                "group_id": "G-1",
                "relation": "HIGH_OVERLAP",
                "member_skill_ids": ["a", "b"],
                "confidence": 0.9,
                "same_points": ["same tool"],
                "recommendations": ["rewrite boundary"],
            }
        ],
        "findings": [{"rule_id": "R001"}],
    }
    (reports / "R-1.json").write_text(json.dumps(payload), encoding="utf-8")
    repositories = FileRepositories(reports)
    assert repositories.reports.latest_summary()["group_count"] == 1
    assert repositories.groups.list_public(relation="HIGH_OVERLAP", limit=5)[0]["group_id"] == "G-1"
    assert repositories.reports.get_public("R-1")["report_id"] == "R-1"

    database = tmp_path / "index.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE marker(value TEXT)")
    config = tmp_path / "config.yaml"
    config.write_text("schema_version: 2\n", encoding="utf-8")
    context = SimpleNamespace(
        python_version=(3, 12, 0),
        path_shadowing=False,
        config_path=config,
        index_path=database,
        reports_path=reports,
        targets_detected=False,
        reviewer_available=False,
        mcp_available=True,
    )
    report = Doctor(context).run()
    assert report.exit_code == 1
    assert {item.code for item in report.checks} == {
        "runtime.version",
        "path.shadowing",
        "config.parse",
        "database.integrity",
        "reports.permissions",
        "targets.detect",
        "reviewers.detect",
        "mcp.handshake",
    }
    assert all(item.status is not CheckStatus.ERROR for item in report.checks)

    broken = SimpleNamespace(
        python_version=(3, 10, 0),
        path_shadowing=True,
        config_error="bad yaml",
        database_integrity=False,
        reports_path=None,
        targets_detected=False,
        reviewer_available=False,
        mcp_available=False,
        restored=False,
        rebuilt=False,
        rewritten=False,
    )
    broken.restore_launcher_path = lambda: setattr(broken, "restored", True)
    broken.rebuild_index = lambda: setattr(broken, "rebuilt", True)
    broken.rewrite_skillcheck_mcp = lambda: setattr(broken, "rewritten", True)
    doctor = Doctor(broken)
    broken_report = doctor.run()
    plan = doctor.plan(broken_report)
    doctor.apply(plan)
    assert broken_report.exit_code == 2
    assert broken.restored and broken.rebuilt and broken.rewritten


def test_source_adapters_keep_directory_zip_and_url_boundaries(tmp_path: Path, monkeypatch) -> None:
    directory = _skill(tmp_path / "directory")
    staged_directory = stage_directory(directory)
    assert staged_directory.root == directory.resolve()
    assert ensure_within(directory.parent, directory) == directory.resolve()
    assert stage_staging_source(directory).root == directory.resolve()
    with pytest.raises(SourceSafetyError):
        stage_directory(tmp_path / "missing")

    archive = tmp_path / "skill.zip"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("demo/SKILL.md", "---\nname: demo\n---\nbody")
    staging_parent = tmp_path / "staging"
    staging_parent.mkdir()
    staged_archive = stage_archive(archive, staging_parent=staging_parent)
    try:
        assert staged_archive.root.name == "demo"
    finally:
        staged_archive.close()
    with pytest.raises(SourceSafetyError):
        stage_archive(tmp_path / "skill.tar")
    monkeypatch.setattr(
        "skillcheck.sources.github._stage_github",
        lambda source, staging_parent: SimpleNamespace(root=tmp_path, close=lambda: None),
    )
    assert stage_github("https://github.com/example/skill").root == tmp_path
    with pytest.raises(SourceSafetyError):
        stage_github("http://github.com/example/skill")
