"""Compatibility exports for the v2 validator core."""

from skillcheck.core.validation import CompositeSkillValidator
from skillcheck.core.validators import BuiltinValidator

__all__ = ["BuiltinValidator", "CompositeSkillValidator"]
