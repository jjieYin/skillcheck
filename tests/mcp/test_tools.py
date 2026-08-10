from __future__ import annotations

from types import SimpleNamespace

import pytest

from skillcheck.governance.models import AnalyzeMode
from skillcheck.mcp.tools import SkillcheckMcpTools
from skillcheck.models.governance import GovernanceDecision, GroupDecision


class Analyzer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def analyze(self, mode, *, source=None, scope="all", limit=20):
        self.calls.append(("analyze", (mode, source, scope, limit)))
        return SimpleNamespace(model_dump=lambda **_: {"mode": str(mode), "source": source, "limit": limit})

    def evidence(self, run_id, group_id, *, page=1, include_body=False):
        self.calls.append(("evidence", (run_id, group_id, page, include_body)))
        return SimpleNamespace(model_dump=lambda **_: {"run_id": run_id, "group_id": group_id, "page": page})


class Reviews:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[GroupDecision]]] = []

    def save(self, run_id, decisions):
        self.calls.append((run_id, decisions))
        return SimpleNamespace(model_dump=lambda **_: {"run_id": run_id, "saved": len(decisions)})


def _tools() -> tuple[SkillcheckMcpTools, Analyzer, Reviews, list[str]]:
    calls: list[str] = []
    analyzer = Analyzer()
    reviews = Reviews()
    runtime = SimpleNamespace(before_query=lambda: calls.append("before_query"))
    return SkillcheckMcpTools(runtime, analyzer=analyzer, reviews=reviews), analyzer, reviews, calls


def test_analyze_validates_source_mode_and_returns_json() -> None:
    tools, analyzer, _, calls = _tools()

    result = tools.analyze("library", None, "all", 20)

    assert result == {"mode": str(AnalyzeMode.LIBRARY), "source": None, "limit": 20}
    assert calls == ["before_query"]
    assert analyzer.calls == [("analyze", (AnalyzeMode.LIBRARY, None, "all", 20))]
    with pytest.raises(ValueError, match="source"):
        tools.analyze("source", None, "all", 20)
    with pytest.raises(ValueError, match="mode"):
        tools.analyze("unknown", None, "all", 20)


def test_evidence_validates_page_and_returns_json() -> None:
    tools, analyzer, _, calls = _tools()

    result = tools.evidence("run-1", "group-1", 0, True)

    assert result == {"run_id": "run-1", "group_id": "group-1", "page": 1}
    assert analyzer.calls == [("evidence", ("run-1", "group-1", 1, True))]
    assert calls == []
    with pytest.raises(ValueError, match="page"):
        tools.evidence("run-1", "group-1", -1, False)


def test_save_review_rejects_malformed_decisions_and_serializes_saved_review() -> None:
    tools, _, reviews, calls = _tools()
    decision = {
        "group_id": "group-1",
        "decision": GovernanceDecision.MERGE.value,
        "canonical_skill": "skill-1",
        "confidence": 0.9,
        "reason": "The documented responsibilities overlap.",
        "recommendations": ["Merge the shared steps."],
    }

    assert tools.save_review("run-1", [decision]) == {"run_id": "run-1", "saved": 1}
    assert calls == []
    assert reviews.calls[0][0] == "run-1"
    assert reviews.calls[0][1][0].decision is GovernanceDecision.MERGE
    with pytest.raises(ValueError):
        tools.save_review("run-1", [{"group_id": "missing-required-fields"}])
