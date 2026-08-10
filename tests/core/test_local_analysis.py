from skillcheck.core.audit import LibraryAuditor
from skillcheck.core.discovery import discover_skills
from skillcheck.core.parser import parse_skill
from skillcheck.core.validators import BuiltinValidator


def test_core_modules_expose_existing_local_engine() -> None:
    assert callable(discover_skills)
    assert callable(parse_skill)
    assert LibraryAuditor is not None
    assert BuiltinValidator is not None
