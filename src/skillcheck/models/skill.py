from pathlib import Path

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
    tools: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    environments: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
