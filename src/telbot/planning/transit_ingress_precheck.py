"""Ingress pre-check: snap + plate solve before transit ingress (obstruction hint for App).

Stable API surface for iOS / other clients — poll ``GET /plan/transit/ingress-precheck``
or read ``ingress_precheck`` on ``GET /plan/transit/status``.

Result schema: ``telbot.transit_ingress_precheck.v1`` (see ``build_precheck_result``).
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
from typing import Any, Literal

from telbot.config import Settings
from telbot.ephem_body import apparent_altaz_star_j2000_deg, apparent_radec_star_j2000_deg
from telbot.models import VoiceIntentV1
from telbot.planning.transit_plan import parse_event_utc_label
from telbot.repo_paths import last_transit_ingress_precheck_path
from telbot.skyfield_data import get_skyfield_loader

SCHEMA_VERSION = "telbot.transit_ingress_precheck.v1"

ReasonCode = Literal[
    "ok",
    "below_horizon",
    "snap_failed",
    "platesolve_failed",
    "pointing_offset",
    "platesolve_unavailable",
    "missing_coordinates",
]

FailPolicy = Literal["continue", "abort"]

_last_precheck: dict[str, Any] | None = None


def angular_separation_arcmin(
    ra1_hours: float,
    dec1_deg: float,
    ra2_hours: float,
    dec2_deg: float,
) -> float:
    """Great-circle separation in arcminutes."""
    r1 = math.radians(ra1_hours * 15.0)
    d1 = math.radians(dec1_deg)
    r2 = math.radians(ra2_hours * 15.0)
    d2 = math.radians(dec2_deg)
    cos_sep = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2)
    cos_sep = min(1.0, max(-1.0, cos_sep))
    return math.degrees(math.acos(cos_sep)) * 60.0


def _user_alert_for_failure(
    *,
    planet: str,
    reason_code: ReasonCode,
    altitude_deg: float | None,
    offset_arcmin: float | None,
    max_offset_arcmin: float,
) -> dict[str, Any]:
    """Structured alert for App UI / push (Chinese copy)."""
    lines: list[str] = []
    if reason_code == "below_horizon":
        lines.append(
            f"预检时刻目标地平高度约 {altitude_deg:.1f}°，低于允许阈值，视场内可能无法正常拍到宿主星。"
        )
        lines.append("常见原因：树木、建筑遮挡，或望远镜摆放位置不当。")
    elif reason_code == "pointing_offset":
        lines.append(
            f"板解中心与预期目标偏差约 {offset_arcmin:.1f}′（允许 {max_offset_arcmin:g}′），"
            "镜筒可能未对准凌星宿主或视场被遮挡。"
        )
        lines.append("请检查周边遮挡并调整望远镜摆放位置后，可再次手动预检或等待后续步骤。")
    elif reason_code in ("platesolve_failed", "snap_failed"):
        lines.append("预检曝光或 ASTAP 板解失败，无法确认目标是否在视场内。")
        lines.append("请检查 CCD 连接、曝光时长、UPLOAD_DIR，以及镜筒前方是否有遮挡。")
    elif reason_code == "platesolve_unavailable":
        lines.append("未安装或未配置 ASTAP 板解，无法自动判断目标是否可拍。")
    else:
        lines.append("凌食开始前预检未通过，请检查望远镜指向与周边遮挡。")

    message = (
        f"凌食开始前约 10 分钟的预检未通过（{planet}）。"
        + (lines[0] if lines else "")
        + " 建议调整望远镜摆放位置，避开遮挡后重新确认。"
    )
    return {
        "severity": "warning",
        "code": "obstruction_suspected",
        "title": "凌食前预检：目标可能无法正常拍摄",
        "message": message,
        "lines": lines,
        "action_hint": "reposition_telescope",
        "show_blocking_dialog": True,
    }


def build_precheck_result(
    *,
    capture_ok: bool,
    reason_code: ReasonCode,
    planet: str,
    check_utc: dt.datetime,
    ingress_utc: dt.datetime,
    expected: dict[str, Any],
    measured: dict[str, Any] | None = None,
    offset_arcmin: float | None = None,
    max_offset_arcmin: float,
    dry_run: bool,
    snap: dict[str, Any] | None = None,
    platesolve: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble ``telbot.transit_ingress_precheck.v1`` payload."""
    alt = expected.get("altitude_deg")
    user_alert: dict[str, Any] | None = None
    if not capture_ok and not dry_run:
        user_alert = _user_alert_for_failure(
            planet=planet,
            reason_code=reason_code,
            altitude_deg=float(alt) if alt is not None else None,
            offset_arcmin=offset_arcmin,
            max_offset_arcmin=max_offset_arcmin,
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "capture_ok": capture_ok,
        "reason_code": reason_code,
        "dry_run": dry_run,
        "planet": planet,
        "check_utc": check_utc.astimezone(dt.timezone.utc).isoformat(),
        "ingress_utc": ingress_utc.astimezone(dt.timezone.utc).isoformat(),
        "minutes_before_ingress": round(
            (ingress_utc - check_utc).total_seconds() / 60.0, 2
        ),
        "expected": expected,
        "measured": measured,
        "offset_arcmin": offset_arcmin,
        "max_offset_arcmin": max_offset_arcmin,
        "snap": snap,
        "platesolve": platesolve,
        "user_alert": user_alert,
        "warnings": warnings or [],
        "ok": capture_ok or dry_run,
    }


def publish_ingress_precheck_result(result: dict[str, Any]) -> Path:
    """Persist and cache the latest precheck for HTTP polling."""
    global _last_precheck
    _last_precheck = result
    p = last_transit_ingress_precheck_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def get_last_ingress_precheck() -> dict[str, Any] | None:
    """Latest precheck from memory or ``data/run/last_transit_ingress_precheck.json``."""
    global _last_precheck
    if _last_precheck is not None:
        return _last_precheck
    p = last_transit_ingress_precheck_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        _last_precheck = data
        return data
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def clear_last_ingress_precheck() -> None:
    global _last_precheck
    _last_precheck = None
    try:
        last_transit_ingress_precheck_path().unlink()
    except FileNotFoundError:
        pass


def _expected_at_check(
    s: Settings,
    *,
    ra_deg: float,
    dec_deg: float,
    when_utc: dt.datetime,
    planet: str,
) -> dict[str, Any]:
    ts = get_skyfield_loader().timescale()
    t = ts.from_datetime(when_utc.astimezone(dt.timezone.utc))
    pos = apparent_radec_star_j2000_deg(
        ra_deg,
        dec_deg,
        t,
        s.latitude,
        s.longitude,
        s.elevation_m,
        planet,
    )
    alt, az = apparent_altaz_star_j2000_deg(
        ra_deg,
        dec_deg,
        t,
        s.latitude,
        s.longitude,
        s.elevation_m,
    )
    return {
        "ra_hours": round(pos.ra_hours, 6),
        "dec_deg": round(pos.dec_deg, 6),
        "altitude_deg": round(alt, 2),
        "azimuth_deg": round(az, 2),
        "frame": "JNOW",
    }


def run_ingress_precheck(
    s: Settings,
    step: dict[str, Any],
    *,
    execute: bool,
    intent_exec_fn: Any | None = None,
) -> dict[str, Any]:
    """
    Execute ``ingress_precheck`` plan step: verify target is capturable before ingress.

    Step fields (from ``build_transit_steps``): ``planet``, ``ra_deg``, ``dec_deg``,
    ``ingress_utc``, ``exposure_seconds``, ``at_utc``.
    """
    planet = str(step.get("planet") or step.get("label") or "target")
    ingress_raw = step.get("ingress_utc_label") or step.get("ingress_utc")
    if not ingress_raw:
        raise ValueError("ingress_precheck 步骤缺少 ingress_utc_label")
    ingress_utc = parse_event_utc_label(str(ingress_raw))
    check_utc = parse_event_utc_label(str(step["at_utc"]))
    ra_deg = float(step["ra_deg"])
    dec_deg = float(step["dec_deg"])
    exp = step.get("exposure_seconds")
    exposure = (
        float(exp)
        if exp is not None
        else (
            float(s.transit_ingress_precheck_exposure_seconds)
            if s.transit_ingress_precheck_exposure_seconds > 0
            else float(s.ccd_default_exposure_seconds)
        )
    )
    max_off = float(s.transit_ingress_precheck_max_offset_arcmin)
    min_alt = min(float(s.min_altitude_deg), float(s.exoplanet_min_altitude_deg))

    expected = _expected_at_check(
        s, ra_deg=ra_deg, dec_deg=dec_deg, when_utc=check_utc, planet=planet
    )
    warnings: list[str] = []

    if not execute:
        out = build_precheck_result(
            capture_ok=True,
            reason_code="ok",
            planet=planet,
            check_utc=check_utc,
            ingress_utc=ingress_utc,
            expected=expected,
            max_offset_arcmin=max_off,
            dry_run=True,
            warnings=[
                f"干跑：将在 {check_utc.isoformat()}（ingress 前约 "
                f"{(ingress_utc - check_utc).total_seconds() / 60:.0f} 分钟）"
                f"曝光 {exposure:g}s 并板解，比对指向偏差（阈值 {max_off:g}′）。"
            ],
        )
        publish_ingress_precheck_result(out)
        return out

    if intent_exec_fn is None:
        from telbot.intent_exec import execute_voice_intent

        intent_exec_fn = execute_voice_intent

    alt = float(expected["altitude_deg"])
    if alt < min_alt:
        out = build_precheck_result(
            capture_ok=False,
            reason_code="below_horizon",
            planet=planet,
            check_utc=check_utc,
            ingress_utc=ingress_utc,
            expected=expected,
            max_offset_arcmin=max_off,
            dry_run=False,
            warnings=[f"目标高度 {alt:.1f}° < 阈值 {min_alt:.1f}°"],
        )
        publish_ingress_precheck_result(out)
        return out

    snap_out = intent_exec_fn(
        s,
        VoiceIntentV1(version=1, action="snap", exposure_seconds=exposure),
        execute=True,
    )
    if not snap_out.get("ok"):
        out = build_precheck_result(
            capture_ok=False,
            reason_code="snap_failed",
            planet=planet,
            check_utc=check_utc,
            ingress_utc=ingress_utc,
            expected=expected,
            max_offset_arcmin=max_off,
            dry_run=False,
            snap=snap_out,
        )
        publish_ingress_precheck_result(out)
        return out

    try:
        from telbot.platesolve.service import run_platesolve
    except ImportError:
        out = build_precheck_result(
            capture_ok=False,
            reason_code="platesolve_unavailable",
            planet=planet,
            check_utc=check_utc,
            ingress_utc=ingress_utc,
            expected=expected,
            max_offset_arcmin=max_off,
            dry_run=False,
            snap=snap_out,
            warnings=["缺少 platesolve 依赖（pip install -e '.[platesolve]'）"],
        )
        publish_ingress_precheck_result(out)
        return out

    ps_out = run_platesolve(s, fits_path=None, use_latest=True)
    if not ps_out.get("ok"):
        out = build_precheck_result(
            capture_ok=False,
            reason_code="platesolve_failed",
            planet=planet,
            check_utc=check_utc,
            ingress_utc=ingress_utc,
            expected=expected,
            max_offset_arcmin=max_off,
            dry_run=False,
            snap=snap_out,
            platesolve=ps_out,
        )
        publish_ingress_precheck_result(out)
        return out

    j_ra = ps_out.get("jnow_ra_hours")
    j_dec = ps_out.get("jnow_dec_deg")
    if j_ra is None or j_dec is None:
        ra_icrs = ps_out.get("ra_icrs_deg")
        dec_icrs = ps_out.get("dec_icrs_deg")
        if ra_icrs is None or dec_icrs is None:
            out = build_precheck_result(
                capture_ok=False,
                reason_code="platesolve_failed",
                planet=planet,
                check_utc=check_utc,
                ingress_utc=ingress_utc,
                expected=expected,
                max_offset_arcmin=max_off,
                dry_run=False,
                snap=snap_out,
                platesolve=ps_out,
                warnings=["板解成功但缺少坐标"],
            )
            publish_ingress_precheck_result(out)
            return out
        ts = get_skyfield_loader().timescale()
        t = ts.from_datetime(check_utc.astimezone(dt.timezone.utc))
        pos = apparent_radec_star_j2000_deg(
            float(ra_icrs),
            float(dec_icrs),
            t,
            s.latitude,
            s.longitude,
            s.elevation_m,
            "solve_center",
        )
        j_ra, j_dec = pos.ra_hours, pos.dec_deg

    measured = {
        "ra_hours": round(float(j_ra), 6),
        "dec_deg": round(float(j_dec), 6),
        "frame": "JNOW",
    }
    offset = angular_separation_arcmin(
        float(expected["ra_hours"]),
        float(expected["dec_deg"]),
        float(j_ra),
        float(j_dec),
    )
    measured["offset_arcmin"] = round(offset, 2)

    if offset > max_off:
        out = build_precheck_result(
            capture_ok=False,
            reason_code="pointing_offset",
            planet=planet,
            check_utc=check_utc,
            ingress_utc=ingress_utc,
            expected=expected,
            measured=measured,
            offset_arcmin=offset,
            max_offset_arcmin=max_off,
            dry_run=False,
            snap=snap_out,
            platesolve=ps_out,
        )
        publish_ingress_precheck_result(out)
        return out

    out = build_precheck_result(
        capture_ok=True,
        reason_code="ok",
        planet=planet,
        check_utc=check_utc,
        ingress_utc=ingress_utc,
        expected=expected,
        measured=measured,
        offset_arcmin=offset,
        max_offset_arcmin=max_off,
        dry_run=False,
        snap=snap_out,
        platesolve=ps_out,
        warnings=warnings,
    )
    publish_ingress_precheck_result(out)
    return out
