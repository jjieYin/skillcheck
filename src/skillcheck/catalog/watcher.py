"""In-process filesystem watcher for catalog roots."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from threading import Event, Lock, Thread, current_thread
from typing import Any

try:
    from watchfiles import watch
except ImportError:  # pragma: no cover - exercised when optional runtime dependency is absent
    def watch(*args: Any, **kwargs: Any):
        raise RuntimeError("watchfiles is unavailable")
        yield set()


class CatalogWatcher:
    """Watch registered roots and deliver each watcher batch once."""

    def __init__(
        self,
        roots: Iterable[Path | str],
        on_changes: Callable[[set[Path]], None],
        debounce_ms: int = 2000,
        *,
        watch_factory: Callable[..., Any] = watch,
    ) -> None:
        self.roots = tuple(Path(root).expanduser().resolve() for root in roots)
        self.on_changes = on_changes
        self.debounce_ms = debounce_ms
        self.watch_factory = watch_factory
        self.warning: str | None = None
        self._stop_event = Event()
        self._lock = Lock()
        self._thread: Thread | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive() and not self._stop_event.is_set()

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self.warning = None
            self._stop_event.clear()
            self._thread = Thread(target=self._run, name="skillcheck-catalog-watcher", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._stop_event.set()
        if thread is not None and thread is not current_thread():
            thread.join(timeout=5)

    def _run(self) -> None:
        try:
            for changes in self.watch_factory(
                *(str(root) for root in self.roots),
                debounce=self.debounce_ms,
                stop_event=self._stop_event,
            ):
                paths = {Path(path).expanduser().resolve() for _, path in changes}
                if paths:
                    self.on_changes(paths)
        except Exception as error:  # noqa: BLE001 - watcher failures are intentionally degraded
            if not self._stop_event.is_set():
                self.warning = str(error)
