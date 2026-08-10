from pathlib import Path
from types import SimpleNamespace

from skillcheck.reviewers.claude import ClaudeReviewAdapter
from skillcheck.reviewers.packet import ReviewPacket


class FakeRunner:
    def __init__(self) -> None:
        self.last_command = []

    def run(self, command, **kwargs):
        self.last_command = command
        return SimpleNamespace(returncode=0, stdout='{"groups":[]}', stderr="")


def test_claude_uses_print_mode_without_session_persistence(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    runner = FakeRunner()
    adapter = ClaudeReviewAdapter(tmp_path / "claude.cmd", runner=runner, schema_path=schema)
    adapter.review(ReviewPacket(packet_id="p1", groups=[]))
    assert "--print" in runner.last_command
    assert "--json-schema" in runner.last_command
    assert "--no-session-persistence" in runner.last_command

