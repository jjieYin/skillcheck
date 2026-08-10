from pathlib import Path

import pytest

from skillcheck.targets.instructions import (
    END,
    START,
    InstructionFormatError,
    InstructionManager,
)


def test_instruction_block_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_text("# Existing\n", encoding="utf-8")
    manager = InstructionManager(path)

    manager.install("Use Skillcheck.")
    manager.install("Use Skillcheck.")

    text = path.read_text(encoding="utf-8")
    assert text.count(START) == 1
    assert text.count(END) == 1
    assert "# Existing\n" in text
    assert "Use Skillcheck." in text


def test_uninstall_removes_only_skillcheck_block(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    original = f"before\n{START}\nold\n{END}\nafter\n"
    path.write_text(original, encoding="utf-8")

    result = InstructionManager(path).uninstall()

    assert result.changed is True
    assert path.read_text(encoding="utf-8") == "before\nafter\n"


def test_uninstall_preserves_crlf_surrounding_bytes(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_bytes(f"before\r\n{START}\r\nold\r\n{END}\r\nafter\r\n".encode())

    InstructionManager(path).uninstall()

    assert path.read_bytes() == b"before\r\nafter\r\n"


def test_install_uses_existing_crlf_without_normalizing_surrounding_bytes(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_bytes(b"before\r\nafter\r\n")

    InstructionManager(path).install("line one\nline two")

    assert path.read_bytes() == (
        b"before\r\nafter\r\n"
        + START.encode()
        + b"\r\nline one\r\nline two\r\n"
        + END.encode()
        + b"\r\n"
    )


@pytest.mark.parametrize(
    "text",
    [f"{START}\nmissing end\n", f"{START}\na\n{END}\n{START}\nb\n{END}\n", f"{END}\n"],
)
def test_malformed_markers_refuse_overwrite(tmp_path: Path, text: str) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_text(text, encoding="utf-8")
    manager = InstructionManager(path)

    with pytest.raises(InstructionFormatError, match="manual repair"):
        manager.preview("Use Skillcheck.")

    assert path.read_text(encoding="utf-8") == text


def test_preview_hash_blocks_changed_instruction_file(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_text("before\n", encoding="utf-8")
    manager = InstructionManager(path)
    preview = manager.preview("Use Skillcheck.")
    path.write_text("changed\n", encoding="utf-8")

    with pytest.raises(RuntimeError):
        manager.apply(preview)

    assert path.read_text(encoding="utf-8") == "changed\n"
