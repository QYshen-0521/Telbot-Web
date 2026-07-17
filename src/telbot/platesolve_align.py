"""Optional mount sync/slew after plate solve (JNow); keeps INDI out of pure solve path."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from telbot.config import Settings
from telbot.horizon import BelowHorizonError, ensure_above_horizon
from telbot.indi import slew_equatorial_eod, sync_equatorial_eod
from telbot.mount_resolve import resolve_telescope_device


def jnow_radec_from_platesolve_out(out: dict[str, Any]) -> tuple[float, float]:
    """
    RA/Dec for EQUATORIAL_EOD / ON_COORD_SET (JNow).
    Requires solve output from run_platesolve with configured observer lat/lon (non-zero).
    """
    j_ra = out.get("jnow_ra_hours")
    j_dec = out.get("jnow_dec_deg")
    if j_ra is None or j_dec is None:
        raise ValueError(
            "自动对准需要解算结果中的 JNow 坐标；请在 .env 配置观测地 "
            "TELBOT_LATITUDE / TELBOT_LONGITUDE（与 mount goto 一致，勿为 0,0）。"
        )
    return float(j_ra), float(j_dec)


def align_mount_after_platesolve(
    s: Settings,
    solve_out: dict[str, Any],
    *,
    align: Literal["sync", "slew"],
    execute: bool,
    on_before_real: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """
    After a successful solve: horizon gate then INDI sync or slew to solution center.
    execute=False → dry_run setprop (no real INDI writes).
    """
    dry_run = not execute
    try:
        ra_h, dec_d = jnow_radec_from_platesolve_out(solve_out)
    except ValueError as e:
        return {
            "mode": align,
            "ok": False,
            "dry_run": dry_run,
            "steps": [],
            "error": str(e),
        }

    try:
        alt = ensure_above_horizon(
            ra_h,
            dec_d,
            latitude_deg=s.latitude,
            longitude_deg=s.longitude,
            elevation_m=s.elevation_m,
            min_altitude_deg=s.min_altitude_deg,
            detail="platesolve 对准",
        )
    except BelowHorizonError as e:
        return {
            "mode": align,
            "ok": False,
            "dry_run": dry_run,
            "steps": [],
            "error": str(e),
        }

    dev = resolve_telescope_device(s)
    steps: list[dict[str, Any]] = [
        {"stage": "resolve", "device": dev, "altitude_deg": alt},
    ]

    if align == "sync":
        r1, r2 = sync_equatorial_eod(
            dev,
            s.indi_host,
            s.indi_port,
            ra_h,
            dec_d,
            dry_run=dry_run,
            on_before_real=on_before_real,
        )
    else:
        r1, r2 = slew_equatorial_eod(
            dev,
            s.indi_host,
            s.indi_port,
            ra_h,
            dec_d,
            dry_run=dry_run,
            on_before_real=on_before_real,
        )

    steps.extend(
        [
            {"stage": "equatorial_eod_coord", "stdout": r1.stdout, "stderr": r1.stderr, "code": r1.returncode},
            {"stage": "on_coord_set", "stdout": r2.stdout, "stderr": r2.stderr, "code": r2.returncode},
        ]
    )

    ok = r1.returncode == 0 and r2.returncode == 0
    return {
        "mode": align,
        "ok": ok,
        "dry_run": dry_run,
        "ra_hours": ra_h,
        "dec_deg": dec_d,
        "steps": steps,
        "error": None if ok else "INDI indi_setprop 非零退出",
    }
