from pathlib import Path

import numpy as np

from skillcheck.config import AppConfig
from skillcheck.reports import ReportWriter
from skillcheck.service import SkillCheckService
from skillcheck.store import SkillStore
from skillcheck.validators import BuiltinValidator
from tests.helpers import write_skill


class FakeEmbedding:
    model_id = "fake-v1"

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.ones((len(texts), 2), dtype=np.float32)


def test_check_without_llm_still_writes_report(tmp_path: Path) -> None:
    fixture_skill = write_skill(tmp_path / "incoming", body="This is a sufficiently long safe skill body.")
    service = SkillCheckService(
        config=AppConfig.default(tmp_path),
        store=SkillStore(tmp_path / "index.db"),
        embedding=FakeEmbedding(),
        validator=BuiltinValidator(),
        skillspector=None,
        reviewer=None,
        report_writer=ReportWriter(tmp_path / "reports"),
    )
    result = service.check(str(fixture_skill), use_llm=False, top_k=5)
    assert result.report.llm_used is False
    assert result.paths.markdown.exists()
    assert result.paths.json.exists()
    assert result.report.source == str(fixture_skill)


def test_scan_then_audit_uses_existing_library_without_new_source(tmp_path: Path) -> None:
    first = write_skill(tmp_path / ".codex" / "skills" / "one", name="one", body="A long shared procedure for API checks.")
    second = write_skill(tmp_path / ".agents" / "skills" / "two", name="two", body="A long shared procedure for API checks.")
    service = SkillCheckService(
        config=AppConfig.default(tmp_path),
        store=SkillStore(tmp_path / "index.db"),
        embedding=FakeEmbedding(),
        validator=BuiltinValidator(),
        skillspector=None,
        reviewer=None,
        report_writer=ReportWriter(tmp_path / "reports"),
    )
    scan = service.scan()
    assert scan.installation_count == 2
    result = service.audit(use_llm=False)
    assert result.paths.json.exists()
    assert result.report.installation_count == 2
    assert first.exists() and second.exists()
