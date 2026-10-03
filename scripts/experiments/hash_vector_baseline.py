"""Reproducible baseline experiment for Skill package hashes and hash embeddings."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from skillcheck.core.candidates import HybridCandidateRetriever
from skillcheck.core.features import PairSignals
from skillcheck.core.parser import parse_skill
from skillcheck.decisions import RuleDecisionEngine
from skillcheck.embeddings import HashEmbeddingBackend, skill_embedding_text
from skillcheck.models import SkillRecord


@dataclass(frozen=True)
class ExperimentRow:
    case: str
    left: str
    right: str
    package_hash_equal: bool
    instruction_hash_equal: bool
    lexical_similarity: float | None
    dense_similarity_256: float
    dense_similarity_1024: float
    dense_similarity_4096: float
    current_semantic_similarity: float
    current_decision: str


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.dot(left, right) / denominator) if denominator else 0.0


def _dense_similarity(left: SkillRecord, right: SkillRecord, dimensions: int) -> float:
    backend = HashEmbeddingBackend(dimensions=dimensions)
    vectors = backend.encode([skill_embedding_text(left), skill_embedding_text(right)])
    return _cosine(vectors[0], vectors[1])


def _signals(left: SkillRecord, right: SkillRecord) -> PairSignals:
    backend = HashEmbeddingBackend(dimensions=256)
    vectors = backend.encode([skill_embedding_text(left), skill_embedding_text(right)])
    pairs = HybridCandidateRetriever(top_k=2).retrieve(
        [left, right],
        {left.skill_id: vectors[0], right.skill_id: vectors[1]},
    )
    pair = tuple(sorted((left.skill_id, right.skill_id)))
    return pairs.get(pair, PairSignals(semantic_similarity=0.0))


def _row(case: str, left_label: str, left: SkillRecord, right_label: str, right: SkillRecord) -> ExperimentRow:
    signals = _signals(left, right)
    decision = RuleDecisionEngine().decide(left, right, signals)
    return ExperimentRow(
        case=case,
        left=left_label,
        right=right_label,
        package_hash_equal=left.content_hash == right.content_hash,
        instruction_hash_equal=left.instruction_hash == right.instruction_hash,
        lexical_similarity=(
            round(signals.lexical_similarity, 6)
            if signals.lexical_similarity is not None
            else None
        ),
        dense_similarity_256=round(_dense_similarity(left, right, 256), 6),
        dense_similarity_1024=round(_dense_similarity(left, right, 1024), 6),
        dense_similarity_4096=round(_dense_similarity(left, right, 4096), 6),
        current_semantic_similarity=round(signals.semantic_similarity, 6),
        current_decision=decision.decision.value,
    )


def _insert_metadata(text: str) -> str:
    lines = text.splitlines()
    closing = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    lines[closing:closing] = ["metadata:", "  experiment: metadata-only"]
    return "\n".join(lines) + "\n"


def _controlled_rows(base_path: Path) -> list[ExperimentRow]:
    with tempfile.TemporaryDirectory(prefix="skillcheck-hash-vector-") as temporary:
        root = Path(temporary)
        base_root = root / "base"
        shutil.copytree(base_path, base_root)
        base = parse_skill(base_root)
        rows: list[ExperimentRow] = []

        variants: list[tuple[str, Path]] = []
        for name in ("exact-copy", "metadata-only", "format-only", "asset-only", "script-only", "negated-rule"):
            destination = root / name
            shutil.copytree(base_path, destination)
            variants.append((name, destination))

        skill_file = root / "metadata-only" / "SKILL.md"
        skill_file.write_text(_insert_metadata(skill_file.read_text(encoding="utf-8")), encoding="utf-8")

        skill_file = root / "format-only" / "SKILL.md"
        formatted = "  \r\n".join(skill_file.read_text(encoding="utf-8").splitlines()) + "  \r\n"
        skill_file.write_bytes(formatted.encode("utf-8"))

        asset = root / "asset-only" / "assets" / "experiment.txt"
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_text("Presentation-only experiment asset.\n", encoding="utf-8")

        script = root / "script-only" / "scripts" / "experiment_behavior.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("raise RuntimeError('behavior changed')\n", encoding="utf-8")

        skill_file = root / "negated-rule" / "SKILL.md"
        text = skill_file.read_text(encoding="utf-8")
        changed = text.replace("ALWAYS find root cause", "NEVER find root cause", 1)
        if changed == text:
            changed += "\nNever perform the primary action described above.\n"
        skill_file.write_text(changed, encoding="utf-8")

        for label, path in variants:
            rows.append(_row(f"controlled:{label}", "base", base, label, parse_skill(path)))
        return rows


def _template_rows(left_path: Path, right_path: Path) -> list[ExperimentRow]:
    left = parse_skill(left_path)
    right = parse_skill(right_path)
    rows = [_row("template:before", "template-left", left, "template-right", right)]
    shared = "\n".join(
        "Before every step, inspect the workspace, validate inputs, record evidence, and wait for confirmation."
        for _ in range(80)
    )
    with tempfile.TemporaryDirectory(prefix="skillcheck-template-") as temporary:
        root = Path(temporary)
        copies: list[Path] = []
        for label, source in (("left", left_path), ("right", right_path)):
            destination = root / label
            shutil.copytree(source, destination)
            skill_file = destination / "SKILL.md"
            skill_file.write_text(
                skill_file.read_text(encoding="utf-8") + "\n## Shared policy\n" + shared + "\n",
                encoding="utf-8",
            )
            copies.append(destination)
        rows.append(
            _row(
                "template:after-shared-boilerplate",
                "template-left+shared",
                parse_skill(copies[0]),
                "template-right+shared",
                parse_skill(copies[1]),
            )
        )
    return rows


def _named_paths(values: Iterable[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        label, separator, raw_path = value.partition("=")
        if not separator or not label or not raw_path:
            raise ValueError(f"invalid --skill value: {value!r}; expected LABEL=PATH")
        result[label] = Path(raw_path).expanduser().resolve()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--skill", action="append", default=[])
    parser.add_argument("--pair", action="append", default=[])
    parser.add_argument("--template-left", required=True, type=Path)
    parser.add_argument("--template-right", required=True, type=Path)
    args = parser.parse_args()

    named = _named_paths(args.skill)
    rows = _controlled_rows(args.base.resolve())
    for value in args.pair:
        case, separator, labels = value.partition("=")
        left_label, comma, right_label = labels.partition(",")
        if not separator or not comma or left_label not in named or right_label not in named:
            raise ValueError(f"invalid --pair value: {value!r}; expected CASE=LEFT,RIGHT")
        rows.append(
            _row(case, left_label, parse_skill(named[left_label]), right_label, parse_skill(named[right_label]))
        )
    rows.extend(_template_rows(args.template_left.resolve(), args.template_right.resolve()))
    print(json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
