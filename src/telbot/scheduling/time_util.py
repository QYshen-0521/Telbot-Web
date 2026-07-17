"""UTC time parsing and blocking wait until a deadline."""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable
from typing import Any


def parse_utc_iso(value: str) -> dt.datetime:
    """Parse ISO 8601 timestamp; require timezone (or Z)."""
    z = value.strip()
    if not z:
        raise ValueError("时间字符串为空")
    d = dt.datetime.fromisoformat(z.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError(f"时间须带时区或使用 Z：{value!r}")
    return d.astimezone(dt.timezone.utc)


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def seconds_until(target_utc: dt.datetime) -> float:
    return (target_utc - utc_now()).total_seconds()


def wait_until_utc(
    target_utc: dt.datetime,
    *,
    poll_seconds: float = 1.0,
    on_tick: Callable[[float], None] | None = None,
    abort_check: Callable[[], None] | None = None,
) -> None:
    """
    Block until ``target_utc`` (UTC-aware).

    ``on_tick(remaining_seconds)`` called each poll; ``abort_check()`` if set
    should raise AbortRequested when stop is requested.
    """
    while True:
        if abort_check is not None:
            abort_check()
        remaining = seconds_until(target_utc)
        if remaining <= 0:
            return
        if on_tick is not None:
            on_tick(remaining)
        time.sleep(min(max(0.05, poll_seconds), remaining))
