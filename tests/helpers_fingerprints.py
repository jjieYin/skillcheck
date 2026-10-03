from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "fingerprints"


@dataclass(frozen=True)
class CaseResult:
    case: str
    expected: object
    actual: object
    passed: bool


def fixture_root(name: str) -> Path:
    path = FIXTURE_ROOT / name
    if not path.is_dir():
        raise AssertionError(f"missing fingerprint fixture: {name}")
    return path


def load_pair(name: str) -> tuple[Path, Path]:
    if name in {"metadata-only", "format-only", "asset-only", "script-only"}:
        return fixture_root(name) / "base", fixture_root(name) / "variant"
    if name == "full-lite":
        return fixture_root("full"), fixture_root("lite")
    if name == "polarity":
        return fixture_root("polarity-required"), fixture_root("polarity-forbidden")
    if name == "shared-boilerplate":
        return fixture_root("shared-boilerplate-a"), fixture_root("shared-boilerplate-b")
    if name == "unrelated":
        return fixture_root("unrelated-a"), fixture_root("unrelated-b")
    if name == "exact-copy":
        root = fixture_root(name)
        return root, root
    raise AssertionError(f"unknown fingerprint fixture pair: {name}")


def run_case(case: str, expected: object, actual: object) -> CaseResult:
    return CaseResult(case=case, expected=expected, actual=actual, passed=expected == actual)
