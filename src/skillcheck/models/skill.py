from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from skillcheck.models.common import Provider, Scope


class SkillRecord(BaseModel):
    skill_id: str
    name: str
    description: str = ""
    root_path: Path
    provider: Provider | None = None
    scope: Scope | None = None
    body: str = ""
    content_hash: str
    instruction_hash: str = ""
    behavior_hash: str = ""
    execution_hash: str | None = None
    hash_algorithm_revision: str = "2"
    license: str = ""
    compatibility: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    environments: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)

    @property
    def package_hash(self) -> str:
        """Read-only v2 name for the legacy complete-package hash."""

        return self.content_hash
