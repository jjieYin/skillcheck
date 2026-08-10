"""Compatibility exports for the v2 parser."""

from skillcheck.core.parser import (
    SkillParseError,
    canonical_skill_bytes,
    content_hash,
    parse_frontmatter,
    parse_skill,
)

__all__ = [
    "SkillParseError",
    "canonical_skill_bytes",
    "content_hash",
    "parse_frontmatter",
    "parse_skill",
]
