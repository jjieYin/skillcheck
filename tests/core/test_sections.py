from __future__ import annotations

from pathlib import Path

from skillcheck.core.sections import extract_skill_sections
from skillcheck.models import SkillRecord


def _skill(body: str) -> SkillRecord:
    return SkillRecord(
        skill_id="sections",
        name="API checker",
        description="Check API responses when validating schemas.",
        root_path=Path("/skills/sections"),
        body=body,
        content_hash="package",
        allowed_tools=["http-client"],
        permissions=["network-read"],
        inputs=["request schema"],
        outputs=["validation report"],
    )


def test_sections_split_markdown_code_and_constraint_polarity() -> None:
    sections = extract_skill_sections(
        _skill(
            "## Procedure\n\nYou must validate fields.\n\n"
            "```python\nprint('check')\n```\n\n"
            "You must not write to the database.\n"
        )
    )

    assert "check api responses" in sections.activation_text
    assert any("print" in chunk for chunk in sections.procedure_chunks)
    assert {clause.polarity for clause in sections.constraint_clauses} == {"required", "forbidden"}
    assert "allowed_tools:http-client" in sections.capability_tokens
    assert "permissions:network-read" in sections.capability_tokens


def test_sections_chunk_long_paragraphs_with_bounded_overlap() -> None:
    sections = extract_skill_sections(_skill("a" * 1700))

    assert len(sections.procedure_chunks) == 3
    assert all(len(chunk) <= 800 for chunk in sections.procedure_chunks)
    assert sections.procedure_chunks[0][-100:] == sections.procedure_chunks[1][:100]
