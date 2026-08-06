from pathlib import Path

import pytest

from skillcheck.installer import InstallBlocked, Installer
from skillcheck.models import Decision
from skillcheck.parser import content_hash
from tests.helpers import check_report, write_skill


@pytest.mark.parametrize("decision", [Decision.MERGE, Decision.REJECT, Decision.UNSAFE])
def test_blocked_decisions_cannot_install(tmp_path: Path, decision: Decision) -> None:
    with pytest.raises(InstallBlocked):
        Installer().install(check_report(decision), target_root=tmp_path, confirmed=True)


def test_changed_source_hash_is_rejected(tmp_path: Path) -> None:
    source = write_skill(tmp_path / "source", body="A safe installation procedure with enough detail.")
    report = check_report(Decision.PASS).model_copy(
        update={"source": str(source), "source_hash": "sha256:changed"}
    )
    with pytest.raises(InstallBlocked, match="hash"):
        Installer().install(report, target_root=tmp_path / "target", confirmed=True)


def test_successful_install_copies_without_overwriting(tmp_path: Path) -> None:
    source = write_skill(tmp_path / "source", name="api-check", body="A safe installation procedure with enough detail.")
    report = check_report(Decision.PASS).model_copy(
        update={"source": str(source), "source_hash": content_hash(source)}
    )
    target = tmp_path / "target"
    installed = Installer().install(report, target_root=target, confirmed=True)
    assert installed == target / "api-check"
    assert (installed / "SKILL.md").is_file()
    with pytest.raises(InstallBlocked, match="exists"):
        Installer().install(report, target_root=target, confirmed=True)


def test_variant_requires_explicit_name(tmp_path: Path) -> None:
    source = write_skill(tmp_path / "source", name="api-check", body="A safe installation procedure with enough detail.")
    report = check_report(Decision.VARIANT).model_copy(
        update={"source": str(source), "source_hash": content_hash(source)}
    )
    with pytest.raises(InstallBlocked, match="name"):
        Installer().install(report, target_root=tmp_path / "target", confirmed=True)
