from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from skillcheck.lifecycle.uninstall import UninstallManager


class FakeContext:
    def __init__(self, tmp_path: Path) -> None:
        self.user_skill = tmp_path / "skills" / "one" / "SKILL.md"
        self.user_skill.parent.mkdir(parents=True)
        self.user_skill.write_text("skill", encoding="utf-8")
        self.index = tmp_path / "index.db"
        self.index.write_text("index", encoding="utf-8")
        self.report = tmp_path / "report.md"
        self.report.write_text("report", encoding="utf-8")
        self.program = tmp_path / "program"
        self.program.mkdir()
        self.calls = []
        self.layout = SimpleNamespace(
            owned_program_paths=lambda: [self.program],
            owned_roots=lambda: [self.program.parent],
        )
        self.targets = SimpleNamespace(configured=lambda: [SimpleNamespace(uninstall=self._uninstall)])
        self.helpers = SimpleNamespace(remove_program_after_exit=lambda paths: self.calls.append(("remove", paths)))
        self.data = SimpleNamespace(remove_selected=lambda plan: self.calls.append(("data", plan)))
        self.results = SimpleNamespace(
            cancelled=lambda: SimpleNamespace(changed=False, message="已取消"),
            completed=lambda plan: SimpleNamespace(changed=True, message="卸载已执行"),
        )

    def _uninstall(self, scope):
        self.calls.append(("target", scope))


def test_default_uninstall_preserves_user_data(tmp_path: Path) -> None:
    context = FakeContext(tmp_path)
    manager = UninstallManager(context)
    plan = manager.plan()
    assert plan.remove_program is True
    assert plan.remove_agent_configs is True
    assert plan.remove_index is False
    assert plan.remove_reports is False
    assert plan.remove_user_config is False
    manager.execute(plan, confirmed=True)
    assert context.user_skill.exists()
    assert context.index.exists()
    assert context.report.exists()


def test_uninstall_rejects_wildcard_path(tmp_path: Path) -> None:
    context = FakeContext(tmp_path)
    plan = context.layout.owned_program_paths()
    plan.append(tmp_path / "*")
    context.layout.owned_program_paths = lambda: plan
    try:
        UninstallManager(context).plan()
    except ValueError as exc:
        assert "通配符" in str(exc)
    else:
        raise AssertionError("wildcard path must be rejected")

