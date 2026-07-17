"""Live-stack capture loop (边拍边叠)."""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path
from typing import Any, Callable

from telbot.ccd_calibration import ccd_set_frame_type
from telbot.ccd_resolve import resolve_ccd_device_from_getprop_stdout
from telbot.config import Settings
from telbot.expose_loop import _resolve_cadence, _snap_to_dir
from telbot.indi import indi_available, run_getprop
from telbot.calibration_masters import CalibrationMasters, write_masters_fits
from telbot.live_stack.accumulator import LiveStackAccumulator
from telbot.live_stack.fits_io import write_fits_stack, write_preview_jpeg
from telbot.live_stack.session import archive_raw_frame, live_stack_session_root
from telbot.platesolve.security import (
    fits_files_in_dir,
    max_fits_mtime_ns_in_dir,
    resolve_new_capture_fits,
)
from telbot.repo_paths import live_stack_preview_jpeg_path, live_stack_status_path
from telbot.scheduling.abort import AbortController, AbortRequested
from telbot.scheduling.time_util import seconds_until, utc_now, wait_until_utc


def _publish_status(payload: dict[str, Any]) -> None:
    from telbot.live_stack.session import write_status

    write_status(live_stack_status_path(), payload)


def _calibration_paths(
    s: Settings,
    *,
    cal_bias_dir: str | None,
    cal_dark_dir: str | None,
    cal_flat_dir: str | None,
) -> tuple[str, str, str]:
    bias = (cal_bias_dir or "").strip() or (s.live_stack_cal_bias_dir or "").strip()
    dark = (cal_dark_dir or "").strip() or (s.live_stack_cal_dark_dir or "").strip()
    flat = (cal_flat_dir or "").strip() or (s.live_stack_cal_flat_dir or "").strip()
    return bias, dark, flat


def _calibration_summary(bias: str, dark: str, flat: str) -> dict[str, Any]:
    return {
        "enabled": bool(bias or dark or flat),
        "bias_dir": bias or None,
        "dark_dir": dark or None,
        "flat_dir": flat or None,
    }


def _load_calibration(bias: str, dark: str, flat: str) -> CalibrationMasters:
    if not bias and not dark and not flat:
        return CalibrationMasters()
    return CalibrationMasters.from_directories(
        bias_dir=bias or None,
        dark_dir=dark or None,
        flat_dir=flat or None,
    )


def run_live_stack(
    s: Settings,
    *,
    duration_seconds: float,
    exposure_seconds: float | None = None,
    cadence_seconds: float | None = None,
    session_tag: str | None = None,
    cal_bias_dir: str | None = None,
    cal_dark_dir: str | None = None,
    cal_flat_dir: str | None = None,
    execute: bool,
    abort: AbortController | None = None,
    on_frame: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """
    Repeat CCD snap for *duration_seconds*, align & accumulate, keep raw FITS, export JPEG preview.

    Preview for App: ``GET /camera/live-stack/preview`` reads ``live_stack_preview.jpg``.
    """
    if duration_seconds <= 0:
        raise ValueError("duration_seconds 须 > 0")
    sec = float(
        exposure_seconds if exposure_seconds is not None else s.ccd_default_exposure_seconds
    )
    if sec <= 0:
        raise ValueError("exposure_seconds 须 > 0")
    cadence = _resolve_cadence(s, sec, cadence_seconds)

    from telbot.live_stack.session import default_session_tag

    tag = (session_tag or s.ccd_session_tag or "").strip() or default_session_tag()
    end = utc_now() + dt.timedelta(seconds=float(duration_seconds))
    cal_bias, cal_dark, cal_flat = _calibration_paths(
        s,
        cal_bias_dir=cal_bias_dir,
        cal_dark_dir=cal_dark_dir,
        cal_flat_dir=cal_flat_dir,
    )
    cal_summary = _calibration_summary(cal_bias, cal_dark, cal_flat)

    if not execute:
        est = max(0, int(duration_seconds // cadence))
        msg = (
            f"干跑：边拍边叠 {duration_seconds:g}s，每帧曝光 {sec:g}s，约 {est} 帧；"
            "真机请加 --execute；依赖 pip install -e \".[livestack]\"."
        )
        if cal_summary["enabled"]:
            msg += f" 将使用校准：{cal_summary}。"
        return {
            "ok": True,
            "dry_run": True,
            "action": "live_stack",
            "schema_version": "telbot.live_stack.v1",
            "exposure_seconds": sec,
            "duration_seconds": duration_seconds,
            "cadence_seconds": cadence,
            "until_utc": end.isoformat(),
            "estimated_frames": est,
            "session_tag": tag,
            "calibration": cal_summary,
            "message": msg,
        }

    from telbot.live_stack.fits_io import require_live_stack_deps

    require_live_stack_deps()

    root = live_stack_session_root(s.ccd_save_dir, tag)
    raw_dir = root / "raw"
    stack_dir = root / "stack"
    preview_dir = root / "preview"
    global_preview = live_stack_preview_jpeg_path()

    ccd = (s.indi_ccd_device or "").strip()
    if indi_available():
        r = run_getprop(s.indi_host, s.indi_port, "*.*.*", timeout=max(s.indi_getprop_timeout, 2.0))
        if r.returncode == 0 and r.stdout:
            ccd = resolve_ccd_device_from_getprop_stdout(s, r.stdout)
    if not ccd:
        raise RuntimeError("TELBOT_INDI_CCD_DEVICE 未设置")
    patched = s.model_copy(update={"indi_ccd_device": ccd})

    try:
        cal_masters = _load_calibration(cal_bias, cal_dark, cal_flat)
    except ValueError as e:
        raise RuntimeError(f"加载校准主帧失败：{e}") from e
    cal_summary = cal_masters.summary()

    acc = LiveStackAccumulator()
    acc._calibration = cal_masters if cal_masters.enabled else None  # noqa: SLF001
    if cal_masters.enabled:
        write_masters_fits(root / "calibration", cal_masters)

    controller = abort or AbortController()
    frames_meta: list[dict[str, Any]] = []
    frame_idx = 0

    _publish_status(
        {
            "ok": True,
            "running": True,
            "schema_version": "telbot.live_stack.v1",
            "session_tag": tag,
            "session_dir": str(root),
            "exposure_seconds": sec,
            "duration_seconds": duration_seconds,
            "cadence_seconds": cadence,
            "until_utc": end.isoformat(),
            "frames_stacked": 0,
            "calibration": cal_summary,
            "preview_url": "/camera/live-stack/preview",
            "status_url": "/camera/live-stack/status",
        }
    )

    try:
        with controller:
            while True:
                controller.check()
                if seconds_until(end) <= 0:
                    break
                frame_idx += 1
                ft = ccd_set_frame_type(
                    ccd,
                    s.indi_host,
                    s.indi_port,
                    "light",
                    dry_run=False,
                    timeout=max(s.indi_getprop_timeout, 2.0),
                )
                if any(r.returncode != 0 for r in ft):
                    return _finish_fail(
                        tag,
                        root,
                        frame_idx,
                        {"steps": [r.returncode for r in ft]},
                        frames_meta,
                        message=f"第 {frame_idx} 帧：无法设置 FRAME_LIGHT",
                    )
                before_paths = fits_files_in_dir(raw_dir)
                before_ns = max_fits_mtime_ns_in_dir(raw_dir)
                snap_out = _snap_to_dir(patched, sec, raw_dir)
                if not snap_out.get("ok"):
                    return _finish_fail(
                        tag,
                        root,
                        frame_idx,
                        snap_out,
                        frames_meta,
                        message=f"第 {frame_idx} 帧曝光失败",
                    )
                new_fits = resolve_new_capture_fits(raw_dir, before_ns, before_paths)
                if new_fits is None:
                    return _finish_fail(
                        tag,
                        root,
                        frame_idx,
                        snap_out,
                        frames_meta,
                        message=f"第 {frame_idx} 帧后未在 {raw_dir} 发现新 FITS",
                    )
                archived = archive_raw_frame(new_fits, raw_dir, frame_idx)
                try:
                    frame_info = acc.add_frame(archived, align=True)
                except Exception as e:
                    return _finish_fail(
                        tag,
                        root,
                        frame_idx,
                        snap_out,
                        frames_meta,
                        message=f"叠加失败：{e}",
                    )
                master = stack_dir / "live_stack_master.fits"
                write_fits_stack(master, acc.sum_array, acc.frame_count)
                preview_session = preview_dir / "latest.jpg"
                write_preview_jpeg(
                    preview_session,
                    acc.sum_array,
                    acc.frame_count,
                    max_size=int(s.live_stack_preview_max_px),
                )
                shutil.copy2(preview_session, global_preview)
                frame_row = {
                    **frame_info,
                    "raw_path": str(archived),
                    "driver_path": str(new_fits),
                }
                frames_meta.append(frame_row)
                status = {
                    "ok": True,
                    "running": True,
                    "schema_version": "telbot.live_stack.v1",
                    "session_tag": tag,
                    "session_dir": str(root),
                    "exposure_seconds": sec,
                    "duration_seconds": duration_seconds,
                    "cadence_seconds": cadence,
                    "until_utc": end.isoformat(),
                    "frames_stacked": acc.frame_count,
                    "calibration": cal_summary,
                    "last_frame": frame_row,
                    "stack_master_fits": str(master),
                    "preview_path": str(preview_session),
                    "preview_url": "/camera/live-stack/preview",
                }
                _publish_status(status)
                if on_frame:
                    on_frame(status)
                if seconds_until(end) <= 0:
                    break
                sleep_for = min(cadence, seconds_until(end))
                wait_until_utc(
                    utc_now() + dt.timedelta(seconds=sleep_for),
                    poll_seconds=min(1.0, sleep_for),
                    abort_check=controller.check,
                )
    except AbortRequested as e:
        out = _finish_ok(
            tag,
            root,
            acc,
            frames_meta,
            aborted=True,
            reason=e.reason,
            cal_summary=cal_summary,
        )
        _publish_status({**out, "running": False})
        return out

    out = _finish_ok(
        tag,
        root,
        acc,
        frames_meta,
        aborted=False,
        reason=None,
        cal_summary=cal_summary,
    )
    _publish_status({**out, "running": False})
    return out


def _finish_ok(
    tag: str,
    root: Path,
    acc: LiveStackAccumulator,
    frames_meta: list[dict],
    *,
    aborted: bool,
    reason: str | None,
    cal_summary: dict[str, Any],
) -> dict[str, Any]:
    msg = f"边拍边叠结束，共叠加 {acc.frame_count} 帧。"
    if aborted:
        msg = f"边拍边叠已中止（{reason}），已叠加 {acc.frame_count} 帧。"
    return {
        "ok": True,
        "dry_run": False,
        "action": "live_stack",
        "schema_version": "telbot.live_stack.v1",
        "aborted": aborted,
        "abort_reason": reason,
        "session_tag": tag,
        "session_dir": str(root),
        "frames_stacked": acc.frame_count,
        "stack_master_fits": str(root / "stack" / "live_stack_master.fits"),
        "calibration": cal_summary if cal_summary.get("enabled") else None,
        "preview_url": "/camera/live-stack/preview",
        "frames": frames_meta,
        "message": msg,
    }


def _finish_fail(
    tag: str,
    root: Path,
    frame_idx: int,
    snap_out: dict,
    frames_meta: list[dict],
    *,
    message: str,
) -> dict[str, Any]:
    payload = {
        "ok": False,
        "running": False,
        "dry_run": False,
        "action": "live_stack",
        "schema_version": "telbot.live_stack.v1",
        "session_tag": tag,
        "session_dir": str(root),
        "frames_stacked": len(frames_meta),
        "frames_completed": frame_idx,
        "last_snap": snap_out,
        "frames": frames_meta,
        "message": message,
        "preview_url": "/camera/live-stack/preview",
    }
    _publish_status(payload)
    return payload
