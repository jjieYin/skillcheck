"""Marker-fenced, compare-and-swap Agent instruction file management."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from skillcheck.targets.config_io import atomic_replace, content_hash

START = "<!-- SKILLCHECK_START -->"
END = "<!-- SKILLCHECK_END -->"


class InstructionFormatError(RuntimeError):
    """Raised when a user-owned instruction file has unsafe marker syntax."""


@dataclass(frozen=True)
class InstructionChange:
    """Hash-bound instruction text ready to be applied."""

    path: Path
    before_hash: str | None
    after_text: str
    changed: bool


@dataclass(frozen=True)
class InstructionWriteResult:
    path: Path
    changed: bool


class InstructionManager:
    """Own exactly one fenced block without modifying surrounding user text."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser()

    def preview(self, instructions: str) -> InstructionChange:
        text = self._read()
        span = self._marker_span(text)
        block = self._block(instructions, self._line_ending(text, span))
        if span is None:
            separator = "" if not text or text.endswith("\n") else "\n"
            after_text = f"{text}{separator}{block}"
        else:
            start, end = span
            after_text = f"{text[:start]}{block}{text[end:]}"
        return InstructionChange(
            path=self.path,
            before_hash=content_hash(self.path),
            after_text=after_text,
            changed=after_text != text,
        )

    def install(self, instructions: str) -> InstructionWriteResult:
        return self.apply(self.preview(instructions))

    def apply(self, change: InstructionChange) -> InstructionWriteResult:
        if change.path != self.path:
            raise ValueError("instruction change belongs to a different path")
        if change.changed:
            atomic_replace(self.path, change.after_text, expected_hash=change.before_hash)
        return InstructionWriteResult(path=self.path, changed=change.changed)

    def uninstall(self) -> InstructionWriteResult:
        return self.apply(self.preview_uninstall())

    def preview_uninstall(self) -> InstructionChange:
        """Build a hash-bound change that removes only Skillcheck's marker block."""

        text = self._read()
        span = self._marker_span(text)
        if span is None:
            after_text = text
        else:
            start, end = span
            after_text = f"{text[:start]}{text[end:]}"
        return InstructionChange(
            path=self.path,
            before_hash=content_hash(self.path),
            after_text=after_text,
            changed=after_text != text,
        )

    def validate(self) -> bool:
        try:
            return self._marker_span(self._read()) is not None
        except InstructionFormatError:
            return False

    def validate_absent(self) -> bool:
        try:
            return self._marker_span(self._read()) is None
        except InstructionFormatError:
            return False

    def _read(self) -> str:
        if not self.path.exists():
            return ""
        # ``Path.read_text`` uses universal-newline mode and silently changes
        # CRLF user content to LF.  Keep the original separators for the
        # compare-and-swap preview and for owned-block removal.
        with self.path.open("r", encoding="utf-8", newline="") as handle:
            return handle.read()

    @staticmethod
    def _block(instructions: str, newline: str) -> str:
        body = instructions.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
        body = body.replace("\n", newline)
        return f"{START}{newline}{body}{newline}{END}{newline}"

    @staticmethod
    def _line_ending(text: str, span: tuple[int, int] | None) -> str:
        sample = text if span is None else text[span[0] : span[1]]
        if "\r\n" in sample:
            return "\r\n"
        if "\r" in sample:
            return "\r"
        return "\n"

    @staticmethod
    def _marker_span(text: str) -> tuple[int, int] | None:
        starts = [index for index in range(len(text)) if text.startswith(START, index)]
        ends = [index for index in range(len(text)) if text.startswith(END, index)]
        if not starts and not ends:
            return None
        if len(starts) != 1 or len(ends) != 1 or starts[0] > ends[0]:
            raise InstructionFormatError(
                "Skillcheck instruction markers are incomplete or duplicated; manual repair is required"
            )
        end = ends[0] + len(END)
        if text.startswith("\r\n", end):
            end += 2
        elif text[end : end + 1] in {"\r", "\n"}:
            end += 1
        return starts[0], end
