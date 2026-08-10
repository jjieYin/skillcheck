"""In-process filesystem watcher for catalog roots."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from threading import Event, Lock, Thread, current_thread
from typing import Any

try:
    from watchfiles import watch
    WATCHFILES_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when optional runtime dependency is absent
    WATCHFILES_AVAILABLE = False

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
        self._startup_complete = Event()
        self._lock = Lock()
        self._thread: Thread | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive() and not self._stop_event.is_set()

    @property
    def startup_error(self) -> str | None:
        """Return an error raised while opening the watch, if any."""
        return self.warning if self._startup_complete.is_set() else None

    @property
    def available(self) -> bool:
        return WATCHFILES_AVAILABLE or self.watch_factory is not watch

    @property
    def startup_pending(self) -> bool:
        return not self._startup_complete.is_set() and self.warning is None

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self.warning = None
            self._stop_event.clear()
            self._startup_complete.clear()
            self._thread = Thread(target=self._run, name="skillcheck-catalog-watcher", daemon=True)
            self._thread.start()
        self._startup_complete.wait(timeout=1)

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._stop_event.set()
        if thread is not None and thread is not current_thread():
            thread.join(timeout=5)

    def _run(self) -> None:
        try:
            options = {"debounce": self.debounce_ms, "stop_event": self._stop_event}
            if self.watch_factory is watch and WATCHFILES_AVAILABLE:
                options.update({"yield_on_timeout": True, "step": 100})
            iterator = iter(
                self.watch_factory(
                    *(str(root) for root in self.roots),
                    **options,
                )
            )
            while not self._stop_event.is_set():
                changes = next(iterator)
                self._startup_complete.set()
                paths = {Path(path).expanduser().resolve() for _, path in changes}
                if paths:
                    self.on_changes(paths)
        except Exception as error:  # noqa: BLE001 - watcher failures are intentionally degraded
            if not self._stop_event.is_set():
                self.warning = str(error)
        finally:
            self._startup_complete.set()
