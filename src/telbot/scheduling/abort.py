"""Cooperative abort for long-running loops (expose_loop, transit execute).

Beyond the simple thread-safe flag, ``AbortController`` can:

* watch an out-of-band **abort flag file** (so another process — e.g.
  ``telbot plan transit-abort`` — can stop a running observation), and
* invoke an **``on_abort`` callback exactly once** the moment an abort is
  triggered (signal, flag file, or :meth:`request`). The transit executor uses
  this to immediately send ``TELESCOPE_ABORT_MOTION`` and halt the mount, even
  if the main thread is currently blocked inside a CCD exposure.
"""

from __future__ import annotations

import signal
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any


class AbortRequested(RuntimeError):
    """Raised when a long task should stop cooperatively."""

    def __init__(self, reason: str = "abort requested") -> None:
        self.reason = reason
        super().__init__(reason)


class AbortController:
    """Thread-safe abort flag; optional SIGINT/SIGTERM hook, flag-file watch, on-abort callback."""

    def __init__(
        self,
        *,
        flag_path: Path | None = None,
        on_abort: Callable[[str], Any] | None = None,
        poll_interval: float = 0.5,
    ) -> None:
        self._event = threading.Event()
        self._reason = "abort requested"
        self._prev_handlers: dict[int, object] = {}
        self._flag_path = flag_path
        self._on_abort = on_abort
        self._poll_interval = max(0.1, float(poll_interval))
        self._on_abort_lock = threading.Lock()
        self._on_abort_fired = False
        self._on_abort_result: Any = None
        self._watch_thread: threading.Thread | None = None
        self._watch_stop = threading.Event()

    @property
    def aborted(self) -> bool:
        return self._event.is_set()

    @property
    def has_on_abort(self) -> bool:
        return self._on_abort is not None

    @property
    def on_abort_fired(self) -> bool:
        return self._on_abort_fired

    @property
    def on_abort_result(self) -> Any:
        return self._on_abort_result

    def set_flag_path(self, path: Path | None) -> None:
        """Set the abort flag file to watch (no-op if one is already configured)."""
        if self._flag_path is None:
            self._flag_path = path

    def set_on_abort(self, callback: Callable[[str], Any] | None) -> None:
        self._on_abort = callback

    def request(self, reason: str = "abort requested") -> None:
        """Mark abort requested. Signal-handler safe (no callback fired here)."""
        self._reason = reason
        self._event.set()

    def reason(self) -> str:
        return self._reason

    def _read_flag_reason(self) -> str:
        if self._flag_path is None:
            return "abort flag"
        try:
            text = self._flag_path.read_text(encoding="utf-8").strip()
        except OSError:
            text = ""
        return text or "abort flag file present"

    def _poll_flag(self) -> None:
        if self._flag_path is not None and not self._event.is_set() and self._flag_path.exists():
            self.request(self._read_flag_reason())

    def _fire_on_abort(self) -> None:
        """Invoke ``on_abort`` at most once (best-effort emergency stop)."""
        if self._on_abort is None:
            return
        with self._on_abort_lock:
            if self._on_abort_fired:
                return
            self._on_abort_fired = True
        try:
            self._on_abort_result = self._on_abort(self._reason)
        except Exception as e:  # emergency stop must not raise back into the watcher
            self._on_abort_result = {"ok": False, "error": str(e)}

    def check(self) -> None:
        """Raise :class:`AbortRequested` if aborted; fire ``on_abort`` once as a fallback."""
        self._poll_flag()
        if self._event.is_set():
            self._fire_on_abort()
            raise AbortRequested(self._reason)

    # --- background watcher: triggers on_abort promptly even mid-exposure ---

    def _watch_loop(self) -> None:
        while not self._watch_stop.is_set():
            self._poll_flag()
            if self._event.is_set():
                self._fire_on_abort()
                return
            self._watch_stop.wait(self._poll_interval)

    def start_watch(self) -> None:
        if self._watch_thread is not None:
            return
        if self._flag_path is None and self._on_abort is None:
            return
        self._watch_stop.clear()
        self._watch_thread = threading.Thread(
            target=self._watch_loop, name="telbot-abort-watch", daemon=True
        )
        self._watch_thread.start()

    def stop_watch(self) -> None:
        self._watch_stop.set()
        t = self._watch_thread
        if t is not None:
            t.join(timeout=2.0)
        self._watch_thread = None

    def install_signal_handlers(self) -> None:
        """Map SIGINT/SIGTERM to cooperative abort (restored on context exit if used as CM)."""

        def _handler(signum: int, _frame: object) -> None:
            name = "SIGINT" if signum == signal.SIGINT else f"signal {signum}"
            self.request(f"{name} received")

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self._prev_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                pass

    def restore_signal_handlers(self) -> None:
        for sig, prev in self._prev_handlers.items():
            try:
                signal.signal(sig, prev)  # type: ignore[arg-type]
            except (ValueError, OSError):
                pass
        self._prev_handlers.clear()

    def __enter__(self) -> AbortController:
        self.install_signal_handlers()
        self.start_watch()
        return self

    def __exit__(self, *_args: object) -> None:
        self.stop_watch()
        self.restore_signal_handlers()
