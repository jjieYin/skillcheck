import shutil
from pathlib import Path

from skillcheck.config import AppConfig
from skillcheck.installer import InstallBlocked, Installer
from skillcheck.parser import content_hash
from skillcheck.reports import ReportWriter
from skillcheck.service import SkillCheckService
from skillcheck.store import SkillStore
from skillcheck.validators import BuiltinValidator
from tests.helpers import check_report
from tests.test_service import FakeEmbedding


def _service(tmp_path: Path) -> SkillCheckService:
    return SkillCheckService(
        config=AppConfig.default(tmp_path),
        store=SkillStore(tmp_path / "index.db"),
        embedding=FakeEmbedding(),
        validator=BuiltinValidator(),
        skillspector=None,
        reviewer=None,
        report_writer=ReportWriter(tmp_path / "reports"),
    )


def test_scan_audit_report_does_not_modify_existing_skills(tmp_path: Path) -> None:
    root = tmp_path / ".codex" / "skills"
    root.mkdir(parents=True)
    shutil.copytree(Path("tests/fixtures/duplicate-a"), root / "duplicate-a")
    shutil.copytree(Path("tests/fixtures/duplicate-b"), root / "duplicate-b")
    before = {
        path: content_hash(path)
        for path in [root / "duplicate-a", root / "duplicate-b"]
    }
    service = _service(tmp_path)
    service.scan(cwd=tmp_path)
    result = service.audit(use_llm=False)
    assert result.paths.markdown.exists()
    assert result.paths.json.exists()
    assert any(group.relation == "EXACT_DUPLICATE" for group in result.report.groups)
    assert before == {path: content_hash(path) for path in before}


def test_check_report_and_confirmed_install_are_hash_bound(tmp_path: Path) -> None:
    source = Path("tests/fixtures/duplicate-a").resolve()
    service = _service(tmp_path)
    result = service.check(str(source), use_llm=False)
    assert result.report.source_hash == content_hash(source)
    installed = Installer().install(result.report, target_root=tmp_path / "installed", confirmed=True)
    assert (installed / "SKILL.md").is_file()
    blocked = check_report().model_copy(
        update={"source": str(source), "source_hash": "sha256:wrong"}
    )
    try:
        Installer().install(blocked, target_root=tmp_path / "blocked", confirmed=True)
    except InstallBlocked:
        pass
    else:
        raise AssertionError("changed source hash must block installation")
