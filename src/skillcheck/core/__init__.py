"""Deterministic Skill discovery, analysis, and validation logic.

Public names are loaded lazily so legacy ``skillcheck.models`` and
``skillcheck.core`` re-exports can safely refer to one another during import.
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "AuditResult",
    "AuditScope",
    "BuiltinValidator",
    "CandidateScore",
    "CompositeSkillValidator",
    "ConstraintClause",
    "HybridCandidateRetriever",
    "LibraryAuditor",
    "PairEvidence",
    "PairSignals",
    "PairSignalsV2",
    "RuleDecision",
    "RuleDecisionEngine",
    "SkillParseError",
    "SkillSections",
    "VectorLike",
    "activation_text",
    "cosine_similarity",
    "cosine_top_k",
    "extract_skill_sections",
    "lexical_features",
    "parse_frontmatter",
    "parse_skill",
    "procedure_text",
]

_EXPORTS = {
    "AuditResult": ("skillcheck.core.audit", "AuditResult"),
    "AuditScope": ("skillcheck.core.audit", "AuditScope"),
    "LibraryAuditor": ("skillcheck.core.audit", "LibraryAuditor"),
    "PairEvidence": ("skillcheck.core.audit", "PairEvidence"),
    "HybridCandidateRetriever": ("skillcheck.core.candidates", "HybridCandidateRetriever"),
    "RuleDecision": ("skillcheck.core.decisions", "RuleDecision"),
    "RuleDecisionEngine": ("skillcheck.core.decisions", "RuleDecisionEngine"),
    "PairSignals": ("skillcheck.core.features", "PairSignals"),
    "PairSignalsV2": ("skillcheck.core.features", "PairSignalsV2"),
    "activation_text": ("skillcheck.core.features", "activation_text"),
    "lexical_features": ("skillcheck.core.features", "lexical_features"),
    "procedure_text": ("skillcheck.core.features", "procedure_text"),
    "SkillSections": ("skillcheck.core.sections", "SkillSections"),
    "ConstraintClause": ("skillcheck.core.sections", "ConstraintClause"),
    "extract_skill_sections": ("skillcheck.core.sections", "extract_skill_sections"),
    "SkillParseError": ("skillcheck.core.parser", "SkillParseError"),
    "parse_frontmatter": ("skillcheck.core.parser", "parse_frontmatter"),
    "parse_skill": ("skillcheck.core.parser", "parse_skill"),
    "BuiltinValidator": ("skillcheck.core.validators", "BuiltinValidator"),
    "CompositeSkillValidator": ("skillcheck.core.validation", "CompositeSkillValidator"),
    "CandidateScore": ("skillcheck.core.retrieval", "CandidateScore"),
    "VectorLike": ("skillcheck.core.retrieval", "VectorLike"),
    "cosine_similarity": ("skillcheck.core.retrieval", "cosine_similarity"),
    "cosine_top_k": ("skillcheck.core.retrieval", "cosine_top_k"),
}


def __getattr__(name: str):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
