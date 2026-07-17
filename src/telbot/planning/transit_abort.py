"""Out-of-band abort signaling for ``telbot plan transit-run``.

The running ``transit-run`` process writes a small *session* file (its PID and
the plan path) and watches an *abort flag* file. Any other process — typically
``telbot plan transit-abort`` — can drop the flag (and optionally signal the
PID) to immediately stop the in-progress observation.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import signal
from pathlib import Path
from typing import Any

from telbot.repo_paths import transit_abort_flag_path, transit_run_session_path


def _ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def write_abort_flag(reason: str = "user requested abort") -> Path:
    """Create the abort flag file watched by a running transit-run."""
    p = transit_abort_flag_path()
    _ensure_parent(p)
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    p.write_text(f"{reason} @ {stamp}\n", encoding="utf-8")
    return p


def clear_abort_flag() -> None:
    try:
        transit_abort_flag_path().unlink()
    except FileNotFoundError:
        pass


def abort_flag_present() -> bool:
    return transit_abort_flag_path().exists()


def write_run_session(plan_path: Path | str | None) -> Path:
    """Record the current process as the active transit-run."""
    p = transit_run_session_path()
    _ensure_parent(p)
    data = {
        "pid": os.getpid(),
        "plan": str(plan_path) if plan_path is not None else None,
        "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def read_run_session() -> dict[str, Any] | None:
    try:
        return json.loads(transit_run_session_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def clear_run_session() -> None:
    try:
        transit_run_session_path().unlink()
    except FileNotFoundError:
        pass


def signal_run_session(sig: int = signal.SIGTERM) -> int | None:
    """Best-effort: send ``sig`` to the recorded transit-run PID.

    Returns the PID that was signaled, or ``None`` if no live session/PID.
    """
    sess = read_run_session()
    if not sess:
        return None
    pid = sess.get("pid")
    if not isinstance(pid, int):
        return None
    try:
        os.kill(pid, sig)
        return pid
    except (ProcessLookupError, PermissionError, OSError):
        return None
