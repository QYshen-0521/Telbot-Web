"""Repeat CCD snap until deadline or duration (expose_loop)."""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from telbot.ccd_indi import ccd_is_connected, ccd_prepare_for_capture, ccd_snap_exposure
from telbot.config import Settings
from telbot.fits_session import prepare_session_capture_dir
from telbot.models import VoiceIntentV1
from telbot.scheduling.abort import AbortController, AbortRequested
from telbot.scheduling.time_util import parse_utc_iso, seconds_until, utc_now, wait_until_utc


def _resolve_cadence(s: Settings, exposure_seconds: float, cadence_seconds: float | None) -> float:
    if cadence_seconds is not None and cadence_seconds > 0:
        return cadence_seconds
    overhead = max(0.0, float(s.expose_loop_overhead_seconds))
    return max(exposure_seconds + overhead, exposure_seconds + 0.5)


def _estimate_frame_count(
    *,
    start_utc: dt.datetime,
    until_utc: dt.datetime,
    cadence_seconds: float,
) -> int:
    span = max(0.0, (until_utc - start_utc).total_seconds())
    if cadence_seconds <= 0:
        return 0
    return max(0, int(span // cadence_seconds))


def run_expose_loop(
    s: Settings,
    *,
    until_utc: dt.datetime | None = None,
    duration_seconds: float | None = None,
    exposure_seconds: float | None = None,
    cadence_seconds: float | None = None,
    session_tag: str | None = None,
    execute: bool,
    abort: AbortController | None = None,
    snap_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Repeat ``snap`` until ``until_utc`` or for ``duration_seconds``.

    Exactly one of ``until_utc`` or ``duration_seconds`` must be set.
    """
    if (until_utc is None) == (duration_seconds is None):
        raise ValueError("须指定 until_utc 或 duration_seconds 之一（不可同时或皆无）")

    sec = float(
        exposure_seconds
        if exposure_seconds is not None
        else s.ccd_default_exposure_seconds
    )
    if sec <= 0:
        raise ValueError("exposure_seconds 须 > 0")

    cadence = _resolve_cadence(s, sec, cadence_seconds)
    now = utc_now()
    if until_utc is None:
        assert duration_seconds is not None
        end = now + dt.timedelta(seconds=float(duration_seconds))
    else:
        end = until_utc.astimezone(dt.timezone.utc)
        if end <= now and execute:
            raise ValueError("until_utc 已过期")

    est_frames = _estimate_frame_count(start_utc=now, until_utc=end, cadence_seconds=cadence)
    tag = (session_tag or s.ccd_session_tag or "").strip() or None

    if not execute:
        return {
            "ok": True,
            "dry_run": True,
            "action": "expose_loop",
            "exposure_seconds": sec,
            "cadence_seconds": cadence,
            "until_utc": end.isoformat(),
            "estimated_frames": est_frames,
            "session_tag": tag,
            "message": (
                f"干跑：将每 {cadence:g}s 曝光 {sec:g}s，直至 {end.isoformat()} "
                f"（约 {est_frames} 帧）。真机请加 --execute。"
            ),
        }

    if snap_fn is None:
        def _snap(settings: Settings, exposure: float, cap_dir: Path | None) -> dict[str, Any]:
            from telbot.intent_exec import execute_voice_intent

            if cap_dir is not None:
                # Direct snap into session folder via temporary override
                patched = settings.model_copy(update={"ccd_save_dir": str(cap_dir)})
                # prepare_ccd_save_directory with exact_dir in intent_exec not supported;
                # use internal snap path below instead
                return _snap_to_dir(patched, exposure, cap_dir)
            return execute_voice_intent(
                settings,
                VoiceIntentV1(version=1, action="snap", exposure_seconds=exposure),
                execute=True,
            )

        snap_fn = _snap

    cap_dir: Path | None = None
    if tag:
        cap_dir = prepare_session_capture_dir(s.ccd_save_dir, tag, dry_run=False)

    settings = s

    controller = abort or AbortController()
    frames: list[dict[str, Any]] = []
    frame_idx = 0
    try:
        with controller:
            while True:
                controller.check()
                remaining = seconds_until(end)
                if remaining <= 0:
                    break
                frame_idx += 1
                snap_out = snap_fn(settings, sec, cap_dir)
                frames.append(
                    {
                        "index": frame_idx,
                        "ok": bool(snap_out.get("ok")),
                        "exposure_seconds": sec,
                    }
                )
                if not snap_out.get("ok"):
                    return {
                        "ok": False,
                        "dry_run": False,
                        "action": "expose_loop",
                        "frames_completed": frame_idx,
                        "last_snap": snap_out,
                        "message": f"第 {frame_idx} 帧曝光失败，expose_loop 中止。",
                        "frames": frames,
                    }
                controller.check()
                remaining = seconds_until(end)
                if remaining <= 0:
                    break
                sleep_for = min(cadence, remaining)
                wait_until_utc(
                    utc_now() + dt.timedelta(seconds=sleep_for),
                    poll_seconds=min(1.0, sleep_for),
                    abort_check=controller.check,
                )
    except AbortRequested as e:
        return {
            "ok": True,
            "dry_run": False,
            "action": "expose_loop",
            "aborted": True,
            "abort_reason": e.reason,
            "frames_completed": frame_idx,
            "until_utc": end.isoformat(),
            "message": f"expose_loop 已中止（{e.reason}），完成 {frame_idx} 帧。",
            "frames": frames,
        }

    return {
        "ok": True,
        "dry_run": False,
        "action": "expose_loop",
        "frames_completed": frame_idx,
        "exposure_seconds": sec,
        "cadence_seconds": cadence,
        "until_utc": end.isoformat(),
        "session_tag": tag,
        "message": f"expose_loop 完成，共 {frame_idx} 帧。",
        "frames": frames,
    }


def parse_until_option(until_iso: str | None, duration_seconds: float | None) -> dt.datetime | None:
    if until_iso:
        return parse_utc_iso(until_iso)
    return None


def _snap_to_dir(s: Settings, exposure_seconds: float, cap_dir: Path) -> dict[str, Any]:
    """Single CCD snap into ``cap_dir`` (session folder)."""
    ccd = (s.indi_ccd_device or "").strip()
    if not ccd:
        raise RuntimeError("TELBOT_INDI_CCD_DEVICE 未设置")
    if not ccd_is_connected(
        ccd, s.indi_host, s.indi_port, timeout=max(s.indi_getprop_timeout, 2.0)
    ):
        raise RuntimeError("CCD 未连接")
    if not os.access(cap_dir, os.W_OK):
        raise RuntimeError(f"CCD 保存目录不可写：{cap_dir}")
    upload_steps = ccd_prepare_for_capture(
        ccd,
        s.indi_host,
        s.indi_port,
        cap_dir,
        dry_run=False,
    )
    rs, meta = ccd_snap_exposure(
        ccd,
        s.indi_host,
        s.indi_port,
        exposure_seconds,
        dry_run=False,
        settle_seconds=s.ccd_snap_settle_seconds,
    )
    ok = all(x.returncode == 0 for x in upload_steps + rs)
    return {
        "ok": ok,
        "action": "snap",
        "device": ccd,
        "exposure_seconds": exposure_seconds,
        "save_dir_hint": str(cap_dir),
        **meta,
    }
