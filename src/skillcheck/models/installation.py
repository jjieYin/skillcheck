from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from skillcheck.models.report import ReportBundle


class InstallationPlan(BaseModel):
    plan_id: str
    source: str
    source_hash: str
    decision: str
    targets: list[str]
    target_paths: list[Path]
    created_at: datetime
    expires_at: datetime
    approval_token: str


class AddOutcome(BaseModel):
    report: ReportBundle
    plan: InstallationPlan
    installed_paths: list[Path] = Field(default_factory=list)


class ReleaseManifest(BaseModel):
    version: str
    platform: str
    architecture: str
    asset_name: str
    sha256: str
    data_schema_version: int
    minimum_compatible_version: str
