from pathlib import Path

import numpy as np

from skillcheck.store import SkillStore


def test_upsert_preserves_vector_when_hash_and_model_match(tmp_path: Path) -> None:
    from tests.helpers import skill_record

    store = SkillStore(tmp_path / "index.db")
    store.upsert(skill_record(), vector=np.array([1.0, 0.0]), model="fake-v1")
    assert store.needs_embedding(skill_record(), "fake-v1") is False


def test_model_change_invalidates_vector(tmp_path: Path) -> None:
    from tests.helpers import skill_record

    store = SkillStore(tmp_path / "index.db")
    store.upsert(skill_record(), vector=np.array([1.0, 0.0]), model="fake-v1")
    assert store.needs_embedding(skill_record(), "fake-v2") is True


def test_replace_inventory_removes_missing_and_exposes_vector_rows(tmp_path: Path) -> None:
    from tests.helpers import skill_record

    store = SkillStore(tmp_path / "index.db")
    first = skill_record(skill_id="first")
    second = skill_record(skill_id="second", root_path=Path("/fixtures/second"))
    store.replace_inventory([first, second], {"first": np.array([1.0, 0.0])}, model="fake-v1")
    store.replace_inventory([first], {}, model="fake-v1")
    assert [skill.skill_id for skill in store.list_skills()] == ["first"]
    rows = store.get_vector_rows(model="fake-v1")
    assert [row.skill_id for row in rows] == ["first"]
