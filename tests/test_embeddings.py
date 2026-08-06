import sys

import numpy as np
import pytest

from skillcheck.embeddings import (
    EmbeddingUnavailable,
    HashEmbeddingBackend,
    SentenceTransformerBackend,
    skill_embedding_text,
)
from skillcheck.models import SkillRecord
from skillcheck.retrieval import cosine_top_k


class FakeEmbedding:
    model_id = "fake-v1"

    def encode(self, texts: list[str]) -> np.ndarray:
        mapping = {"api": [1.0, 0.0], "docs": [0.0, 1.0]}
        return np.asarray([mapping[text] for text in texts], dtype=np.float32)


def test_cosine_search_returns_most_similar_first() -> None:
    rows = [("api-skill", np.array([1.0, 0.0])), ("docs-skill", np.array([0.0, 1.0]))]
    assert cosine_top_k(np.array([0.9, 0.1]), rows, 2)[0].skill_id == "api-skill"


def test_hash_backend_is_deterministic_and_normalized() -> None:
    backend = HashEmbeddingBackend(dimensions=32)
    first = backend.encode(["api", "docs"])
    second = backend.encode(["api", "docs"])
    assert np.array_equal(first, second)
    assert np.allclose(np.linalg.norm(first, axis=1), 1.0)


def test_skill_embedding_text_contains_governance_fields() -> None:
    skill = SkillRecord(
        skill_id="api",
        name="api-check",
        description="Check APIs",
        root_path="/tmp/api",
        body="Send a GET request",
        content_hash="sha256:a",
        tools=["http-client"],
        permissions=["network-read"],
        environments=["test"],
    )
    text = skill_embedding_text(skill)
    assert "api-check" in text
    assert "http-client" in text
    assert "network-read" in text


def test_optional_sentence_transformer_backend_reports_missing_dependency(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(EmbeddingUnavailable):
        SentenceTransformerBackend("local-model")
