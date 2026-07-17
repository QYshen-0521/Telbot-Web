"""Execute VoiceIntentV1 and GOTO-by-body against INDI (used by HTTP and future voice service)."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from telbot.skyfield_data import get_skyfield_loader

from telbot.ccd_paths import effective_ccd_save_dir
from telbot.config import Settings
from telbot.ephem_body import apparent_radec_jnow, apparent_radec_star_j2000_deg
from telbot.horizon import BelowHorizonError, ensure_above_horizon
from telbot.ccd_indi import ccd_is_connected, ccd_prepare_for_capture, ccd_snap_exposure
from telbot.ccd_paths import prepare_ccd_save_directory
from telbot.cfw_indi import (
    DEFAULT_FILTER_SLOTS,
    cfw_connect,
    cfw_get_slot,
    cfw_is_connected,
    cfw_set_slot,
    list_filter_slots,
    resolve_filter_slot,
)
from telbot.focuser_indi import (
    focuser_connect,
    focuser_get_absolute_position,
    focuser_get_max_position,
    focuser_is_connected,
    focuser_move_relative,
)
from telbot.indi import (
    IndiResult,
    abort_motion,
    connect_telescope,
    park_telescope,
    read_equatorial_eod,
    slew_equatorial_eod,
    unpark_telescope,
)
from telbot.models import VoiceIntentV1
from telbot.mount_resolve import resolve_telescope_device
from telbot.intent_nl import attach_intent_nl
from telbot.usb_devices import list_connected_usb_devices


def _step(r: IndiResult) -> dict[str, Any]:
    return {"stdout": r.stdout, "stderr": r.stderr, "code": r.returncode}


def resolve_apparent_for_goto(
    s: Settings,
    name: str,
    t,
) -> Any:
    """Solar system body (DE421) or star catalog (HYG) → ApparentRADec."""
    try:
        return apparent_radec_jnow(
            name,
            t,
            s.latitude,
            s.longitude,
            s.elevation_m,
        )
    except KeyError:
        from telbot.catalog import find_star

        ra_deg, dec_deg, label = find_star(name)
        return apparent_radec_star_j2000_deg(
            ra_deg,
            dec_deg,
            t,
            s.latitude,
            s.longitude,
            s.elevation_m,
            label,
        )


def _once(callback: Callable[[], None] | None) -> Callable[[], None] | None:
    if callback is None:
        return None
    done = False

    def fire() -> None:
        nonlocal done
        if not done:
            done = True
            callback()

    return fire


def _focuser_device(s: Settings) -> str:
    foc = (s.indi_focuser_device or "").strip()
    if not foc:
        raise RuntimeError(
            "TELBOT_INDI_FOCUSER_DEVICE（indi_focuser_device）未设置，请在 .env 中配置电调设备名（如 Oasis Focuser）。"
        )
    return foc


def _cfw_device(s: Settings) -> str:
    cfw = (s.indi_cfw_device or "").strip()
    if not cfw:
        raise RuntimeError(
            "TELBOT_INDI_CFW_DEVICE（indi_cfw_device）未设置，请在 .env 中配置滤镜轮设备名（如 QHYCFW3）。"
        )
    return cfw


def _ensure_cfw_connected(
    s: Settings,
    cfw: str,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None,
) -> list[dict[str, Any]]:
    if dry_run:
        r = cfw_connect(cfw, s.indi_host, s.indi_port, dry_run=True, on_before_real=on_before_real)
        return [_step(r)]
    if cfw_is_connected(
        cfw,
        s.indi_host,
        s.indi_port,
        timeout=max(s.indi_getprop_timeout, 2.0),
    ):
        return []
    r = cfw_connect(
        cfw,
        s.indi_host,
        s.indi_port,
        dry_run=False,
        on_before_real=on_before_real,
    )
    return [_step(r)]


def _slot_label(slot: int) -> str:
    return DEFAULT_FILTER_SLOTS.get(slot, str(slot))


def _ensure_focuser_connected(
    s: Settings,
    foc: str,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None,
) -> list[dict[str, Any]]:
    if dry_run:
        r = focuser_connect(foc, s.indi_host, s.indi_port, dry_run=True, on_before_real=on_before_real)
        return [_step(r)]
    if focuser_is_connected(
        foc,
        s.indi_host,
        s.indi_port,
        timeout=max(s.indi_getprop_timeout, 2.0),
    ):
        return []
    r = focuser_connect(
        foc,
        s.indi_host,
        s.indi_port,
        dry_run=False,
        on_before_real=on_before_real,
    )
    return [_step(r)]


def _gate_horizon(s: Settings, ra_hours: float, dec_deg: float, detail: str = "") -> float:
    return ensure_above_horizon(
        ra_hours,
        dec_deg,
        latitude_deg=s.latitude,
        longitude_deg=s.longitude,
        elevation_m=s.elevation_m,
        min_altitude_deg=s.min_altitude_deg,
        detail=detail,
    )


def slew_body_to_equatorial(
    s: Settings,
    body_name: str,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None = None,
) -> tuple[dict[str, Any], tuple[IndiResult, IndiResult]]:
    """Ephemeris or catalog → RA/Dec → horizon check → slew_equatorial_eod."""
    ts = get_skyfield_loader().timescale()
    t = ts.now()
    pos = resolve_apparent_for_goto(s, body_name.strip(), t)
    meta = {
        "label": pos.label,
        "ra_hours": pos.ra_hours,
        "dec_deg": pos.dec_deg,
    }
    alt = _gate_horizon(s, pos.ra_hours, pos.dec_deg, detail=f"目标={body_name!r}")
    meta["altitude_deg"] = alt
    r1, r2 = slew_equatorial_eod(
        resolve_telescope_device(s),
        s.indi_host,
        s.indi_port,
        pos.ra_hours,
        pos.dec_deg,
        dry_run=dry_run,
        on_before_real=on_before_real,
    )
    return meta, (r1, r2)


def execute_voice_intent(
    s: Settings,
    intent: VoiceIntentV1 | dict[str, Any],
    *,
    execute: bool,
    on_real_indi_start: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """
    Run structured intent. Returns JSON-serializable dict (ok, dry_run, steps, …)
    plus ``nl`` and optional ``nl_simple`` (natural-language summaries for App).
    """
    return attach_intent_nl(
        _execute_voice_intent_raw(
            s,
            intent,
            execute=execute,
            on_real_indi_start=on_real_indi_start,
        )
    )


def _execute_voice_intent_raw(
    s: Settings,
    intent: VoiceIntentV1 | dict[str, Any],
    *,
    execute: bool,
    on_real_indi_start: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if not isinstance(intent, VoiceIntentV1):
        intent = VoiceIntentV1.model_validate(intent)

    if intent.action == "describe":
        tg = (intent.target or "").strip()
        if not tg:
            raise RuntimeError("describe 需要非空 target")
        from telbot.object_intro import build_object_introduction

        return build_object_introduction(s, tg)

    if intent.action == "help":
        from telbot.product_help import build_product_help

        return build_product_help()

    if intent.action == "usb_devices":
        from telbot.usb_devices import format_usb_devices_message

        devices = list_connected_usb_devices()
        message = format_usb_devices_message(devices)
        return {
            "ok": True,
            "dry_run": not execute,
            "action": "usb_devices",
            "devices": devices,
            "count": len(devices),
            "message": message,
        }

    if intent.action == "exoplanet_transits":
        from telbot.exoplanet_transits import build_exoplanet_transit_report

        return build_exoplanet_transit_report(s)

    if intent.action == "plan_exoplanet_transit":
        from telbot.planning.transit_plan import (
            build_transit_plan,
            format_transit_plan_summary,
            save_transit_plan_json,
        )

        payload = build_transit_plan(
            s,
            planet=(intent.target or "").strip() or None,
            event_index=intent.event_index,
        )
        path = save_transit_plan_json(payload)
        summary = format_transit_plan_summary(payload, s)
        out: dict[str, Any] = {
            "ok": True,
            "dry_run": not execute,
            "action": "plan_exoplanet_transit",
            "plan": payload,
            "saved_path": str(path.resolve()),
            "message": summary,
            "summary": summary,
        }
        if intent.event_index is not None:
            out["event_index"] = int(intent.event_index)
        return out

    if intent.action == "preflight":
        from telbot.preflight import run_preflight

        return run_preflight(s)

    dry_run = not execute
    hook = _once(on_real_indi_start)

    if intent.action == "snap":
        ccd = (s.indi_ccd_device or "").strip()
        if not ccd:
            raise RuntimeError(
                "TELBOT_INDI_CCD_DEVICE（indi_ccd_device）未设置，请在 .env 中配置 CCD 设备名（如 QHY CCD QHY174M、ZWO CCD ASI294MC Pro）。"
            )
        sec = (
            intent.exposure_seconds
            if intent.exposure_seconds is not None
            else s.ccd_default_exposure_seconds
        )
        if not dry_run and not ccd_is_connected(
            ccd,
            s.indi_host,
            s.indi_port,
            timeout=max(s.indi_getprop_timeout, 2.0),
        ):
            raise RuntimeError(
                "CCD 未连接（CONNECTION.CONNECT 非 On）。请在 Ekos 中 Connect 或执行 "
                "`telbot camera connect --execute`。"
            )
        cap_dir = prepare_ccd_save_directory(s.ccd_save_dir, dry_run=dry_run)
        save_note = str(cap_dir)
        if not dry_run and not os.access(cap_dir, os.W_OK):
            raise RuntimeError(f"CCD 保存目录不可写：{cap_dir}")
        upload_steps = ccd_prepare_for_capture(
            ccd,
            s.indi_host,
            s.indi_port,
            cap_dir,
            dry_run=dry_run,
            on_before_real=hook,
        )
        rs, meta = ccd_snap_exposure(
            ccd,
            s.indi_host,
            s.indi_port,
            sec,
            dry_run=dry_run,
            settle_seconds=s.ccd_snap_settle_seconds,
            on_before_real=hook,
        )
        ok = all(x.returncode == 0 for x in upload_steps + rs)
        out: dict[str, Any] = {
            "ok": ok,
            "dry_run": dry_run,
            "action": "snap",
            "device": ccd,
            "exposure_seconds": sec,
            "steps": [_step(x) for x in upload_steps + rs],
            **meta,
        }
        out["save_dir_hint"] = save_note
        out["capture_date"] = cap_dir.name
        out["indi_upload_dir_hint"] = (
            "已设置 UPLOAD_SETTINGS.UPLOAD_DIR=" + save_note + "（UPLOAD_MODE.UPLOAD_LOCAL=On）"
        )
        return out

    dev = resolve_telescope_device(s)

    if intent.action == "connect":
        r = connect_telescope(
            dev,
            s.indi_host,
            s.indi_port,
            dry_run=dry_run,
            on_before_real=hook,
        )
        ok = r.returncode == 0
        return {
            "ok": ok,
            "dry_run": dry_run,
            "action": "connect",
            "device": dev,
            "steps": [_step(r)],
        }

    if intent.action == "unpark":
        r = unpark_telescope(
            dev,
            s.indi_host,
            s.indi_port,
            dry_run=dry_run,
            on_before_real=hook,
        )
        ok = r.returncode == 0
        return {
            "ok": ok,
            "dry_run": dry_run,
            "action": "unpark",
            "device": dev,
            "steps": [_step(r)],
        }

    if intent.action == "platesolve":
        from telbot.platesolve.security import (
            fits_files_in_dir,
            max_fits_mtime_ns_in_dir,
            resolve_new_capture_fits,
        )
        from telbot.platesolve.service import run_platesolve

        ccd = (s.indi_ccd_device or "").strip()
        if not ccd:
            raise RuntimeError(
                "TELBOT_INDI_CCD_DEVICE（indi_ccd_device）未设置，请在 .env 中配置 CCD 设备名（如 QHY CCD QHY174M、ZWO CCD ASI294MC Pro）。"
            )
        sec = (
            intent.exposure_seconds
            if intent.exposure_seconds is not None
            else s.ccd_default_exposure_seconds
        )
        if not dry_run and not ccd_is_connected(
            ccd,
            s.indi_host,
            s.indi_port,
            timeout=max(s.indi_getprop_timeout, 2.0),
        ):
            raise RuntimeError(
                "CCD 未连接（CONNECTION.CONNECT 非 On）。请在 Ekos 中 Connect 或执行 "
                "`telbot camera connect --execute`。"
            )
        cap_dir = prepare_ccd_save_directory(s.ccd_save_dir, dry_run=dry_run)
        if not dry_run and not os.access(cap_dir, os.W_OK):
            raise RuntimeError(f"CCD 保存目录不可写：{cap_dir}")
        before_paths = fits_files_in_dir(cap_dir) if not dry_run else frozenset()
        before_ns = max_fits_mtime_ns_in_dir(cap_dir) if not dry_run else 0
        upload_steps = ccd_prepare_for_capture(
            ccd,
            s.indi_host,
            s.indi_port,
            cap_dir,
            dry_run=dry_run,
            on_before_real=hook,
        )
        rs, meta = ccd_snap_exposure(
            ccd,
            s.indi_host,
            s.indi_port,
            sec,
            dry_run=dry_run,
            settle_seconds=s.ccd_snap_settle_seconds,
            on_before_real=hook,
        )
        snap_ok = all(x.returncode == 0 for x in upload_steps + rs)
        snap_part: dict[str, Any] = {
            "ok": snap_ok,
            "dry_run": dry_run,
            "device": ccd,
            "exposure_seconds": sec,
            "steps": [_step(x) for x in upload_steps + rs],
            **meta,
            "save_dir_hint": str(cap_dir),
            "capture_date": cap_dir.name,
        }
        if not snap_ok:
            return {
                "ok": False,
                "dry_run": dry_run,
                "action": "platesolve",
                "snap": snap_part,
            }
        if dry_run:
            dry_out: dict[str, Any] = {
                "ok": True,
                "dry_run": True,
                "action": "platesolve",
                "snap": snap_part,
                "solve": {
                    "ok": False,
                    "skipped": "dry_run",
                    "message": "干跑不执行 ASTAP；真机请加 --execute（text/listen）或 HTTP execute=true",
                },
            }
            if intent.platesolve_align is not None:
                dry_out["align"] = {
                    "mode": intent.platesolve_align,
                    "ok": False,
                    "skipped": "dry_run",
                    "message": "干跑不对望远镜做 SYNC/SLEW；真机 execute=true 且解算成功后再对准",
                }
            return dry_out
        new_fits = resolve_new_capture_fits(cap_dir, before_ns, before_paths)
        if new_fits is None:
            return {
                "ok": False,
                "dry_run": dry_run,
                "action": "platesolve",
                "snap": snap_part,
                "message": (
                    f"曝光后在 {cap_dir} 未检测到新的 FITS；"
                    "请确认 UPLOAD_SETTINGS.UPLOAD_DIR 与该目录一致且 UPLOAD_MODE.UPLOAD_LOCAL=On"
                ),
            }
        try:
            solve_out = run_platesolve(s, fits_path=new_fits, use_latest=False)
        except ImportError as e:
            return {
                "ok": False,
                "dry_run": dry_run,
                "action": "platesolve",
                "snap": snap_part,
                "message": str(e),
            }
        out = dict(solve_out)
        out["action"] = "platesolve"
        out["snap"] = snap_part
        out["ok"] = bool(solve_out.get("ok")) and snap_ok
        if intent.platesolve_align is not None:
            if not out["ok"]:
                out["align"] = {
                    "mode": intent.platesolve_align,
                    "ok": False,
                    "skipped": "solve_not_ok",
                    "error": "解算未成功，跳过对准",
                }
            else:
                from telbot.platesolve_align import align_mount_after_platesolve

                out["align"] = align_mount_after_platesolve(
                    s,
                    solve_out,
                    align=intent.platesolve_align,
                    execute=not dry_run,
                    on_before_real=hook,
                )
                out["ok"] = out["ok"] and bool(out["align"].get("ok", False))
        return out

    if intent.action == "park":
        r = park_telescope(
            dev,
            s.indi_host,
            s.indi_port,
            dry_run=dry_run,
            on_before_real=hook,
        )
        ok = r.returncode == 0
        return {
            "ok": ok,
            "dry_run": dry_run,
            "action": "park",
            "device": dev,
            "steps": [_step(r)],
        }

    if intent.action == "abort":
        r = abort_motion(
            dev,
            s.indi_host,
            s.indi_port,
            dry_run=dry_run,
            on_before_real=hook,
        )
        ok = r.returncode == 0
        return {
            "ok": ok,
            "dry_run": dry_run,
            "action": "abort",
            "device": dev,
            "steps": [_step(r)],
        }

    if intent.action == "focuser_position":
        foc = _focuser_device(s)
        steps_out: list[dict[str, Any]] = []
        if not dry_run:
            steps_out.extend(
                _ensure_focuser_connected(s, foc, dry_run=False, on_before_real=hook)
            )
        rc_pos, pos, raw_p = focuser_get_absolute_position(
            foc, s.indi_host, s.indi_port, timeout=s.indi_getprop_timeout
        )
        rc_max, mx, raw_m = focuser_get_max_position(
            foc, s.indi_host, s.indi_port, timeout=s.indi_getprop_timeout
        )
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "action": "focuser_position",
                "device": foc,
                "message": "将读取 ABS_FOCUS_POSITION 与 FOCUS_MAX",
            }
        if rc_pos != 0 or pos is None:
            raise RuntimeError(f"无法读取电调位置：{raw_p or raw_m}")
        out: dict[str, Any] = {
            "ok": True,
            "dry_run": False,
            "action": "focuser_position",
            "device": foc,
            "position": int(pos),
            "steps": steps_out,
        }
        if rc_max == 0 and mx is not None:
            out["max"] = int(mx)
        return out

    if intent.action == "focuser_rel":
        foc = _focuser_device(s)
        direction = intent.focuser_direction
        steps_n = intent.focuser_steps
        assert direction is not None and steps_n is not None
        steps_out = _ensure_focuser_connected(s, foc, dry_run=dry_run, on_before_real=hook)
        rel_results = focuser_move_relative(
            foc,
            s.indi_host,
            s.indi_port,
            steps_n,
            direction,
            dry_run=dry_run,
            on_before_real=hook,
        )
        steps_out.extend(_step(r) for r in rel_results)
        ok = all(r.returncode == 0 for r in rel_results)
        out_rel: dict[str, Any] = {
            "ok": ok,
            "dry_run": dry_run,
            "action": "focuser_rel",
            "device": foc,
            "focuser_direction": direction,
            "focuser_steps": steps_n,
            "steps": steps_out,
        }
        if not dry_run and ok:
            _rc, pos_after, _ = focuser_get_absolute_position(
                foc, s.indi_host, s.indi_port, timeout=s.indi_getprop_timeout
            )
            if pos_after is not None:
                out_rel["position_after"] = int(pos_after)
        return out_rel

    if intent.action == "focuser_autofocus":
        from telbot.autofocus import run_autofocus

        foc = _focuser_device(s)

        def _ensure_foc() -> None:
            _ensure_focuser_connected(s, foc, dry_run=False, on_before_real=hook)

        return run_autofocus(
            s,
            execute=execute,
            exposure_seconds=intent.exposure_seconds,
            on_before_real=hook,
            ensure_focuser_connected=_ensure_foc if not dry_run else None,
        )

    if intent.action == "cfw_current":
        cfw = _cfw_device(s)
        steps_out: list[dict[str, Any]] = []
        if not dry_run:
            steps_out.extend(_ensure_cfw_connected(s, cfw, dry_run=False, on_before_real=hook))
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "action": "cfw_current",
                "device": cfw,
                "message": "将读取 FILTER_SLOT.FILTER_SLOT_VALUE",
            }
        rc, slot, raw = cfw_get_slot(
            cfw, s.indi_host, s.indi_port, timeout=max(s.indi_getprop_timeout, 2.0)
        )
        if rc != 0 or slot is None:
            raise RuntimeError(f"无法读取当前滤镜槽：{raw}")
        return {
            "ok": True,
            "dry_run": False,
            "action": "cfw_current",
            "device": cfw,
            "slot": slot,
            "name": _slot_label(slot),
            "steps": steps_out,
        }

    if intent.action == "cfw_list":
        cfw = _cfw_device(s)
        filters = list_filter_slots()
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "action": "cfw_list",
                "device": cfw,
                "filters": filters,
            }
        return {
            "ok": True,
            "dry_run": False,
            "action": "cfw_list",
            "device": cfw,
            "filters": filters,
        }

    if intent.action == "cfw_goto":
        cfw = _cfw_device(s)
        raw_target = (intent.target or "").strip()
        try:
            slot = resolve_filter_slot(raw_target)
        except ValueError as e:
            raise RuntimeError(str(e)) from e
        label = _slot_label(slot)
        steps_out = _ensure_cfw_connected(s, cfw, dry_run=dry_run, on_before_real=hook)
        r = cfw_set_slot(
            cfw,
            s.indi_host,
            s.indi_port,
            slot,
            dry_run=dry_run,
            on_before_real=hook,
        )
        steps_out.append(_step(r))
        out_goto: dict[str, Any] = {
            "ok": r.returncode == 0,
            "dry_run": dry_run,
            "action": "cfw_goto",
            "device": cfw,
            "slot": slot,
            "name": label,
            "target": raw_target,
            "steps": steps_out,
        }
        if not dry_run and r.returncode == 0:
            _rc, slot_after, _ = cfw_get_slot(
                cfw, s.indi_host, s.indi_port, timeout=max(s.indi_getprop_timeout, 2.0)
            )
            if slot_after is not None:
                out_goto["slot_after"] = slot_after
        return out_goto

    if intent.action == "nudge":
        cur = read_equatorial_eod(
            dev,
            s.indi_host,
            s.indi_port,
            timeout=s.indi_getprop_timeout,
        )
        if cur is None:
            raise RuntimeError("无法读取当前 EQUATORIAL_EOD_COORD，请确认已 CONNECT。")
        ra0, dec0 = cur
        dra = s.nudge_step_ra_hours
        ddec = s.nudge_step_dec_deg
        direction = intent.nudge_direction
        assert direction is not None
        ra1, dec1 = ra0, dec0
        if direction == "up":
            dec1 = dec0 + ddec
        elif direction == "down":
            dec1 = dec0 - ddec
        elif direction == "left":
            ra1 = (ra0 - dra) % 24.0
        else:
            ra1 = (ra0 + dra) % 24.0
        dec1 = max(-90.0, min(90.0, dec1))
        resolved = {
            "from": {"ra_hours": ra0, "dec_deg": dec0},
            "to": {"ra_hours": ra1, "dec_deg": dec1},
            "direction": direction,
        }
        alt = _gate_horizon(s, ra1, dec1, detail="微移后")
        resolved["altitude_deg"] = alt
        r1, r2 = slew_equatorial_eod(
            dev,
            s.indi_host,
            s.indi_port,
            ra1,
            dec1,
            dry_run=dry_run,
            on_before_real=hook,
        )
        ok = r1.returncode == 0 and r2.returncode == 0
        return {
            "ok": ok,
            "dry_run": dry_run,
            "action": "nudge",
            "device": dev,
            "resolved": resolved,
            "steps": [_step(r1), _step(r2)],
        }

    # goto
    assert intent.action == "goto"
    if intent.target and intent.target.strip():
        meta, (r1, r2) = slew_body_to_equatorial(
            s,
            intent.target.strip(),
            dry_run=dry_run,
            on_before_real=hook,
        )
        ok = r1.returncode == 0 and r2.returncode == 0
        return {
            "ok": ok,
            "dry_run": dry_run,
            "action": "goto",
            "mode": "body",
            "device": dev,
            "resolved": meta,
            "steps": [_step(r1), _step(r2)],
        }

    ra_h = intent.ra_hours
    dec_d = intent.dec_deg
    assert ra_h is not None and dec_d is not None
    resolved = {"ra_hours": ra_h, "dec_deg": dec_d}
    alt = _gate_horizon(s, ra_h, dec_d, detail="坐标 GOTO")
    resolved["altitude_deg"] = alt
    r1, r2 = slew_equatorial_eod(
        dev,
        s.indi_host,
        s.indi_port,
        ra_h,
        dec_d,
        dry_run=dry_run,
        on_before_real=hook,
    )
    ok = r1.returncode == 0 and r2.returncode == 0
    return {
        "ok": ok,
        "dry_run": dry_run,
        "action": "goto",
        "mode": "radec",
        "device": dev,
        "resolved": resolved,
        "steps": [_step(r1), _step(r2)],
    }
