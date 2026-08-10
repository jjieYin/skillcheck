from pathlib import Path
from types import SimpleNamespace

from skillcheck.reviewers.codex import CodexReviewAdapter
from skillcheck.reviewers.packet import ReviewPacket


class FakeRunner:
    def __init__(self) -> None:
        self.last_command = []
        self.last_stdin = None

    def run(self, command, **kwargs):
        self.last_command = command
        self.last_stdin = kwargs["input"]
        return SimpleNamespace(returncode=0, stdout='{"groups":[]}', stderr="")


def test_codex_uses_ephemeral_read_only_json_invocation(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    runner = FakeRunner()
    adapter = CodexReviewAdapter(tmp_path / "codex.cmd", runner=runner, schema_path=schema)
    packet = ReviewPacket(packet_id="p1", groups=[])
    execution = adapter.review(packet)
    assert execution.returncode == 0
    assert runner.last_command[0].lower().endswith(("codex.cmd", "codex.exe"))
    assert ["exec", "--ephemeral", "--sandbox", "read-only"] == runner.last_command[1:5]
    assert runner.last_stdin == packet.model_dump_json()

