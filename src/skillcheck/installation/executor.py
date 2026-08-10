from __future__ import annotations

from pathlib import Path

from skillcheck.installation.rollback import InstallationRollback
from skillcheck.installer import Installer
from skillcheck.models import CheckReport, InstallationPlan


class InstallationExecutor:
    def __init__(
        self,
        installer: Installer | None = None,
        rollback: InstallationRollback | None = None,
    ) -> None:
        self.installer = installer or Installer()
        self.rollback = rollback or InstallationRollback()

    def execute(self, report: CheckReport, plan: InstallationPlan) -> list[Path]:
        installed: list[Path] = []
        try:
            for target_root in plan.target_paths:
                installed.append(
                    self.installer.install(
                        report,
                        target_root=target_root,
                        confirmed=True,
                    )
                )
        except Exception:
            self.rollback.remove_created(installed)
            raise
        return installed
