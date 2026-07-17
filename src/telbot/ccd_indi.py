"""INDI CCD: connection check and single exposure via CCD_EXPOSURE (e.g. SBIG, ZWO ASI, QHY)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pathlib import Path

from telbot.indi import IndiResult, run_getprop, run_setprop


def ccd_parse_connection_connected(stdout: str) -> bool:
    """True if CONNECTION.CONNECT=On appears in getprop output."""
    for line in stdout.splitlines():
        line = line.strip()
        if ".CONNECTION.CONNECT=" in line:
            return line.rstrip().endswith("=On")
    return False


def ccd_is_connected(
    device: str,
    host: str,
    port: int,
    *,
    timeout: float,
) -> bool:
    pattern = f"{device}.CONNECTION.CONNECT"
    r = run_getprop(host, port, pattern, timeout=timeout)
    if r.returncode != 0:
        return False
    return ccd_parse_connection_connected(r.stdout)


def ccd_connect(
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


def ccd_disconnect(
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


def ccd_configure_upload(
    device: str,
    host: str,
    port: int,
    upload_dir: Path,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None = None,
    setprop_timeout: float = 30.0,
) -> list[IndiResult]:
    """Point INDI local upload to *upload_dir* (absolute) before exposure."""
    path_str = str(upload_dir.expanduser().resolve())
    r_dir = run_setprop(
        host,
        port,
        f"{device}.UPLOAD_SETTINGS.UPLOAD_DIR={path_str}",
        dry_run=dry_run,
        timeout=setprop_timeout,
        on_before_real=on_before_real,
    )
    # INDI 2.x CCD: UPLOAD_MODE switch (UPLOAD_LOCAL / UPLOAD_BOTH / UPLOAD_CLIENT).
    r_mode = run_setprop(
        host,
        port,
        f"{device}.UPLOAD_MODE.UPLOAD_LOCAL=On",
        dry_run=dry_run,
        timeout=setprop_timeout,
    )
    if not dry_run and r_mode.returncode != 0:
        r_mode = run_setprop(
            host,
            port,
            f"{device}.UPLOAD_SETTINGS.UPLOAD_LOCAL=On",
            dry_run=dry_run,
            timeout=setprop_timeout,
        )
    return [r_dir, r_mode]


def ccd_prepare_for_capture(
    device: str,
    host: str,
    port: int,
    upload_dir: Path,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None = None,
) -> list[IndiResult]:
    """Create *upload_dir* (if needed) and sync INDI UPLOAD_DIR."""
    if not dry_run:
        upload_dir.mkdir(parents=True, exist_ok=True)
    return ccd_configure_upload(
        device,
        host,
        port,
        upload_dir,
        dry_run=dry_run,
        on_before_real=on_before_real,
    )


def ccd_preset_exposure_seconds(
    device: str,
    host: str,
    port: int,
    exposure_seconds: float,
    *,
    dry_run: bool = False,
    setprop_timeout: float = 30.0,
) -> IndiResult:
    """Set ``CCD_EXPOSURE.CCD_EXPOSURE_VALUE`` only (does not wait for exposure to finish)."""
    if exposure_seconds <= 0:
        raise ValueError("exposure_seconds must be > 0")
    spec_value = f"{device}.CCD_EXPOSURE.CCD_EXPOSURE_VALUE={exposure_seconds}"
    return run_setprop(
        host,
        port,
        spec_value,
        dry_run=dry_run,
        timeout=setprop_timeout,
    )


def ccd_snap_exposure(
    device: str,
    host: str,
    port: int,
    exposure_seconds: float,
    *,
    dry_run: bool,
    settle_seconds: float = 3.0,
    setprop_timeout: float = 30.0,
    on_before_real: Callable[[], None] | None = None,
) -> tuple[list[IndiResult], dict[str, Any]]:
    """
    Set CCD_EXPOSURE.CCD_EXPOSURE_VALUE and rely on INDI driver to start exposure
    (standard INDI::CCD ISNewNumber → StartExposure). After a real setprop, wait
    exposure + settle (indi_getprop does not reliably expose Busy state on all drivers).
    """
    if exposure_seconds <= 0:
        raise ValueError("exposure_seconds must be > 0")

    spec_value = f"{device}.CCD_EXPOSURE.CCD_EXPOSURE_VALUE={exposure_seconds}"
    r_value = run_setprop(
        host,
        port,
        spec_value,
        dry_run=dry_run,
        timeout=setprop_timeout,
        on_before_real=on_before_real,
    )
    steps: list[IndiResult] = [r_value]
    meta: dict[str, Any] = {"waited": False}
    if dry_run or r_value.returncode != 0:
        return steps, meta
    wait = float(exposure_seconds) + float(settle_seconds)
    time.sleep(wait)
    meta["waited"] = True
    meta["wait_seconds"] = wait
    return steps, meta
