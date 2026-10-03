"""Evaluate segmented retrieval/relations without touching a Skill catalog.

This is an experiment harness, not a production migration command.  It loads
portable fixture packages, runs the same section extractor, candidate retriever
and rule engine used by governance analysis, and emits bounded metrics.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from skillcheck.core.candidates import ChannelThresholdProfile, MultiChannelCandidateRetriever
from skillcheck.core.decisions import RuleDecisionEngine
from skillcheck.core.sections import extract_skill_sections
from skillcheck.core.parser import parse_skill
from skillcheck.embeddings import EmbeddingUnavailable, SentenceTransformerVectorizationBackend
from skillcheck.models import Decision, SkillRecord


CASE_EXPECTED: dict[str, str] = {
    "exact-copy": "EXACT_DUPLICATE",
    "metadata-only": "BEHAVIOR_DUPLICATE_CANDIDATE",
    "format-only": "BEHAVIOR_DUPLICATE_CANDIDATE",
    "asset-only": "BEHAVIOR_DUPLICATE_CANDIDATE",
    "script-only": "IMPLEMENTATION_VARIANT_CANDIDATE",
    "polarity": "CONSTRAINT_MISMATCH_CANDIDATE",
    "full-lite": "CONTAINMENT_CANDIDATE",
    "unrelated": "PASS",
    "shared-boilerplate": "PASS",
}


@dataclass(frozen=True)
class PairResult:
    case: str
    expected: str
    predicted: str
    candidate: bool
    relation_score: float | None


def evaluate_fixture(
    fixture_root: Path,
    *,
    backend: str = "hash",
    model_id: str | None = None,
    dimensions: int = 256,
    threshold_profile: str | None = None,
) -> dict[str, object]:
    """Return JSON-ready per-case and per-relation evaluation metrics."""

    vectorizer_kind = "lexical_hash"
    backend_note = "offline deterministic lexical hash"
    if backend != "hash":
        if backend not in {"sentence-transformers", "local"}:
            raise ValueError("backend must be hash, sentence-transformers, or local")
        try:
            SentenceTransformerVectorizationBackend(
                model_id or "sentence-transformers/all-MiniLM-L6-v2",
                dimensions=dimensions,
            )
        except EmbeddingUnavailable as error:
            return {
                "backend": backend,
                "vectorizer_kind": "semantic",
                "status": "unavailable",
                "error": str(error),
                "cases": [],
                "metrics": {},
            }
        vectorizer_kind = "semantic"
        backend_note = model_id or "local sentence-transformers model"

    thresholds = ChannelThresholdProfile(
        semantic_calibrated=threshold_profile is not None if vectorizer_kind == "semantic" else True
    )
    retriever = MultiChannelCandidateRetriever(top_k=20, thresholds=thresholds)
    decisions = RuleDecisionEngine()
    pair_results: list[PairResult] = []
    for case, expected in CASE_EXPECTED.items():
        left_path, right_path = _pair_paths(fixture_root, case)
        left = parse_skill(left_path)
        right = parse_skill(right_path)
        left = left.model_copy(update={"skill_id": f"{case}:left"})
        right = right.model_copy(update={"skill_id": f"{case}:right"})
        skills = [left, right]
        sections = {skill.skill_id: extract_skill_sections(skill) for skill in skills}
        candidates = retriever.retrieve(
            skills,
            sections,
            vectorizer_kind=vectorizer_kind,
        )
        pair = tuple(sorted((left.skill_id, right.skill_id)))
        signals = candidates.get(pair)
        if signals is None:
            predicted = "PASS"
            score = None
            candidate = False
        else:
            result = decisions.decide(left, right, signals)
            predicted = result.relation
            score = result.relation_score
            candidate = True
        pair_results.append(
            PairResult(case, expected, predicted, candidate, score)
        )

    metrics = _metrics(pair_results)
    boilerplate = next(item for item in pair_results if item.case == "shared-boilerplate")
    return {
        "status": "complete",
        "backend": backend,
        "backend_note": backend_note,
        "vectorizer_kind": vectorizer_kind,
        "threshold_profile": threshold_profile,
        "cases": [asdict(item) for item in pair_results],
        "metrics": metrics,
        "recall_at_20": sum(item.candidate for item in pair_results if item.expected != "PASS")
        / max(1, sum(item.expected != "PASS" for item in pair_results)),
        "boilerplate_high_overlap_false_positive_rate": float(
            boilerplate.predicted == "HIGH_OVERLAP_CANDIDATE"
        ),
    }


def _metrics(results: list[PairResult]) -> dict[str, dict[str, float | int]]:
    labels = sorted(set(CASE_EXPECTED.values()) | {item.predicted for item in results})
    metrics: dict[str, dict[str, float | int]] = {}
    for label in labels:
        true_positive = sum(item.expected == label and item.predicted == label for item in results)
        false_positive = sum(item.expected != label and item.predicted == label for item in results)
        false_negative = sum(item.expected == label and item.predicted != label for item in results)
        precision = true_positive / max(1, true_positive + false_positive)
        recall = true_positive / max(1, true_positive + false_negative)
        f1 = 2 * precision * recall / max(1e-12, precision + recall)
        metrics[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": sum(item.expected == label for item in results),
        }
    return metrics


def _pair_paths(root: Path, case: str) -> tuple[Path, Path]:
    if case in {"metadata-only", "format-only", "asset-only", "script-only"}:
        return root / case / "base", root / case / "variant"
    if case == "full-lite":
        return root / "full", root / "lite"
    if case == "polarity":
        return root / "polarity-required", root / "polarity-forbidden"
    if case == "shared-boilerplate":
        return root / "shared-boilerplate-a", root / "shared-boilerplate-b"
    if case == "unrelated":
        return root / "unrelated-a", root / "unrelated-b"
    if case == "exact-copy":
        return root / "exact-copy", root / "exact-copy"
    raise ValueError(f"unknown fixture case: {case}")


def _markdown(payload: dict[str, object]) -> str:
    lines = [
        "# Segmented vector evaluation",
        "",
        f"- status: `{payload.get('status')}`",
        f"- backend: `{payload.get('backend')}` ({payload.get('backend_note', '')})",
        f"- Recall@20: `{float(payload.get('recall_at_20', 0)):.3f}`",
        f"- shared-boilerplate high-overlap false-positive rate: `{float(payload.get('boilerplate_high_overlap_false_positive_rate', 0)):.3f}`",
        "",
        "## Per relation",
        "",
    ]
    for relation, metric in (payload.get("metrics") or {}).items():
        lines.append(
            f"- `{relation}`: precision={metric['precision']:.3f}, "
            f"recall={metric['recall']:.3f}, f1={metric['f1']:.3f}, support={metric['support']}"
        )
    lines.extend(["", "## Cases", ""])
    for case in payload.get("cases", []):
        lines.append(
            f"- `{case['case']}`: expected `{case['expected']}`, "
            f"predicted `{case['predicted']}`, candidate={case['candidate']}"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-dir", type=Path, default=ROOT / "tests" / "fixtures" / "fingerprints")
    parser.add_argument("--backend", default="hash")
    parser.add_argument("--model-id")
    parser.add_argument("--dimensions", type=int, default=256)
    parser.add_argument("--threshold-profile")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    payload = evaluate_fixture(
        args.fixture_dir,
        backend=args.backend,
        model_id=args.model_id,
        dimensions=args.dimensions,
        threshold_profile=args.threshold_profile,
    )
    rendered = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.format == "json"
        else _markdown(payload)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if payload.get("status") == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
