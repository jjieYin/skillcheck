from __future__ import annotations

from pathlib import Path
from threading import Event

from skillcheck.catalog.watcher import CatalogWatcher


def test_watcher_start_stop_and_start_are_idempotent(tmp_path: Path) -> None:
    released = Event()
    calls: list[set[Path]] = []

    def watch_factory(*roots, **kwargs):
        assert roots == (str(tmp_path.resolve()),)
        while not kwargs["stop_event"].is_set():
            released.wait(0.01)
            if released.is_set():
                yield {("modified", str(tmp_path / "example" / "SKILL.md"))}
                return

    watcher = CatalogWatcher([tmp_path], calls.append, watch_factory=watch_factory)
    watcher.start()
    watcher.start()
    released.set()
    while not calls:
        released.wait(0.01)
    watcher.stop()
    watcher.stop()

    assert calls == [{(tmp_path / "example" / "SKILL.md").resolve()}]
    assert watcher.running is False


def test_watcher_keeps_warning_when_watch_factory_fails(tmp_path: Path) -> None:
    def broken_watch(*args, **kwargs):
        raise OSError("watch unavailable")
        yield  # pragma: no cover

    watcher = CatalogWatcher([tmp_path], lambda _: None, watch_factory=broken_watch)
    watcher.start()
    watcher.stop()

    assert watcher.warning == "watch unavailable"
    assert watcher.running is False
