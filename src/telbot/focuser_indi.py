"""INDI focuser (e.g. Astroasis Oasis): connect, position, relative/absolute move."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from telbot.indi import IndiResult, run_getprop, run_setprop

FocuserDirection = Literal["in", "out"]


def _parse_prop_number(stdout: str, element_suffix: str) -> float | None:
    for line in stdout.splitlines():
        line = line.strip()
        if element_suffix in line and "=" in line:
            val = line.rsplit("=", 1)[-1].strip()
            try:
                return float(val)
            except ValueError:
                return None
    return None


def focuser_is_connected(
    device: str,
    host: str,
    port: int,
    *,
    timeout: float,
) -> bool:
    pattern = f"{device}.CONNECTION.*"
    r = run_getprop(host, port, pattern, timeout=timeout)
    if r.returncode != 0:
        return False
    for line in (r.stdout or "").splitlines():
        if ".CONNECTION.CONNECT=" in line:
            return line.rstrip().endswith("=On")
    return False


def focuser_connect(
    device: str,
    host: str,
    port: int,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None = None,
) -> IndiResult:
    return run_setprop(
        host,
        port,
        f"{device}.CONNECTION.CONNECT=On",
        dry_run=dry_run,
        on_before_real=on_before_real,
    )


def focuser_disconnect(
    device: str,
    host: str,
    port: int,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None = None,
) -> IndiResult:
    return run_setprop(
        host,
        port,
        f"{device}.CONNECTION.DISCONNECT=On",
        dry_run=dry_run,
        on_before_real=on_before_real,
    )


def focuser_get_absolute_position(
    device: str,
    host: str,
    port: int,
    *,
    timeout: float = 10.0,
) -> tuple[int, float | None, str]:
    pattern = f"{device}.ABS_FOCUS_POSITION.FOCUS_ABSOLUTE_POSITION"
    r = run_getprop(host, port, pattern, timeout=timeout)
    if r.returncode != 0:
        return r.returncode, None, r.stderr or r.stdout
    return r.returncode, _parse_prop_number(r.stdout, "FOCUS_ABSOLUTE_POSITION"), r.stdout


def focuser_get_max_position(
    device: str,
    host: str,
    port: int,
    *,
    timeout: float = 10.0,
) -> tuple[int, float | None, str]:
    pattern = f"{device}.FOCUS_MAX.FOCUS_MAX_VALUE"
    r = run_getprop(host, port, pattern, timeout=timeout)
    if r.returncode != 0:
        return r.returncode, None, r.stderr or r.stdout
    return r.returncode, _parse_prop_number(r.stdout, "FOCUS_MAX_VALUE"), r.stdout


def focuser_move_absolute(
    device: str,
    host: str,
    port: int,
    position: int,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None = None,
) -> IndiResult:
    return run_setprop(
        host,
        port,
        f"{device}.ABS_FOCUS_POSITION.FOCUS_ABSOLUTE_POSITION={position}",
        dry_run=dry_run,
        on_before_real=on_before_real,
    )


def focuser_wait_settled(
    device: str,
    host: str,
    port: int,
    *,
    timeout: float = 60.0,
    poll_interval: float = 0.5,
    stable_reads: int = 3,
    getprop_timeout: float = 10.0,
) -> float:
    """Poll absolute position until stable; return final position."""
    import time

    last: float | None = None
    stable = 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        _rc, pos, _ = focuser_get_absolute_position(
            device, host, port, timeout=getprop_timeout
        )
        if pos is None:
            time.sleep(poll_interval)
            continue
        if last is not None and abs(pos - last) < 0.5:
            stable += 1
            if stable >= stable_reads:
                return pos
        else:
            stable = 0
        last = pos
        time.sleep(poll_interval)
    raise TimeoutError(f"电调 {device!r} 在 {timeout}s 内未稳定")


def focuser_move_relative(
    device: str,
    host: str,
    port: int,
    steps: int,
    direction: FocuserDirection,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None = None,
) -> list[IndiResult]:
    if steps <= 0:
        raise ValueError("steps must be > 0")
    motion = "FOCUS_INWARD" if direction == "in" else "FOCUS_OUTWARD"
    r1 = run_setprop(
        host,
        port,
        f"{device}.REL_FOCUS_POSITION.FOCUS_RELATIVE_POSITION={steps}",
        dry_run=dry_run,
        on_before_real=on_before_real,
    )
    if dry_run or r1.returncode != 0:
        r2 = run_setprop(
            host,
            port,
            f"{device}.FOCUS_MOTION.{motion}=On",
            dry_run=dry_run,
        )
        return [r1, r2]
    r2 = run_setprop(
        host,
        port,
        f"{device}.FOCUS_MOTION.{motion}=On",
        dry_run=False,
    )
    return [r1, r2]
