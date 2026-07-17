"""INDI CCD calibration frames (bias / dark / flat / light)."""

from __future__ import annotations

import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from telbot.ccd_indi import (
    ccd_is_connected,
    ccd_prepare_for_capture,
    ccd_snap_exposure,
)
from telbot.ccd_paths import capture_date_folder_name, ccd_captures_base_dir
from telbot.config import Settings
from telbot.fits_session import slugify_session_tag
from telbot.indi import IndiResult, indi_available, run_getprop, run_setprop
from telbot.calibration.service import (
    calibration_abort_controller,
    clear_calibration_abort_flag,
)
from telbot.planning.window import observer_timezone
from telbot.scheduling.abort import AbortRequested
from telbot.platesolve.security import (
    capture_before_state,
    exposure_capture_search_dirs,
    fits_probe_for_dirs,
    resolve_new_capture_fits_in_dirs,
)

CalibrationKind = Literal["bias", "dark", "flat", "light"]

# INDI standard CCD_FRAME_TYPE switch elements (docs.indilib.org drivers/standard-properties)
_FRAME_TYPE_CANDIDATES: dict[CalibrationKind, list[str]] = {
    "light": ["FRAME_LIGHT", "LIGHT"],
    "bias": ["FRAME_BIAS", "BIAS"],
    "dark": ["FRAME_DARK", "DARK"],
    "flat": ["FRAME_FLAT", "FLAT"],
}

# Some drivers expose type under CCD_FRAME (non-standard); probed as fallback.
_FRAME_PROPERTY_NAMES = ("CCD_FRAME_TYPE", "CCD_FRAME")


def _default_exposure(s: Settings, kind: CalibrationKind) -> float:
    if kind == "bias":
        return float(s.cal_bias_exposure_seconds)
    if kind == "dark":
        v = float(s.cal_dark_exposure_seconds)
        return v if v > 0 else float(s.ccd_default_exposure_seconds)
    if kind == "flat":
        return float(s.cal_flat_exposure_seconds)
    return float(s.ccd_default_exposure_seconds)


def _default_count(s: Settings, kind: CalibrationKind) -> int:
    base = int(s.cal_default_count)
    if kind == "bias":
        return int(s.cal_bias_count) if s.cal_bias_count > 0 else max(base, 20)
    if kind == "dark":
        return int(s.cal_dark_count) if s.cal_dark_count > 0 else base
    if kind == "flat":
        return int(s.cal_flat_count) if s.cal_flat_count > 0 else max(base, 20)
    return int(s.cal_light_count) if s.cal_light_count > 0 else base


def calibration_archived_filename(kind: CalibrationKind, index: int) -> str:
    """归档文件名：``bias_0001.fits`` / ``dark_0002.fits`` / ``flat_0003.fits``。"""
    return f"{kind}_{index:04d}.fits"


def calibration_save_dir(
    ccd_save_dir_setting: str,
    kind: CalibrationKind,
    session_tag: str,
    *,
    create: bool = True,
) -> Path:
    """``<captures>/<YYYYMMDD>/<kind>_<HHMM>/``（如 ``bias_1129/``）。"""
    base = ccd_captures_base_dir(ccd_save_dir_setting)
    day = capture_date_folder_name()
    slug = slugify_session_tag(session_tag)
    path = (base / day / f"{kind}_{slug}").resolve()
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def calibration_session_time_tag(s: Settings, *, when: datetime | None = None) -> str:
    """App/CLI 下达命令时刻的 4 位本地时间 ``HHMM``（受 ``TELBOT_PLAN_TIMEZONE`` 影响）。"""
    now = when or datetime.now().astimezone()
    tz = observer_timezone(s)
    return now.astimezone(tz).strftime("%H%M")


def default_calibration_session_tag(kind: CalibrationKind, *, s: Settings | None = None) -> str:
    """默认会话后缀：4 位 ``HHMM``；帧类型由目录前缀 ``bias_`` / ``dark_`` / ``flat_`` 表达。"""
    del kind
    if s is not None:
        return calibration_session_time_tag(s)
    return datetime.now().astimezone().strftime("%H%M")


def allocate_calibration_session_slug(
    ccd_save_dir_setting: str,
    kind: CalibrationKind,
    session_tag: str,
) -> str:
    """
    解析并分配会话目录后缀。

    默认同分钟内第二次拍摄会使用 ``1129_2`` 等，避免覆盖已有 ``bias_1129/``。
    """
    slug = slugify_session_tag(session_tag)
    base = ccd_captures_base_dir(ccd_save_dir_setting) / capture_date_folder_name()
    if not (base / f"{kind}_{slug}").exists():
        return slug
    for n in range(2, 100):
        alt = f"{slug}_{n}"
        if not (base / f"{kind}_{alt}").exists():
            return alt
    raise RuntimeError(f"当日 {kind} 会话目录过多，请手动指定 --session")


def effective_calibration_settle_seconds(s: Settings, exposure_seconds: float) -> float:
    """与 ``_snap_calibration_to_dir`` 一致的读出/落盘等待（秒）。"""
    settle = float(s.ccd_snap_settle_seconds)
    if exposure_seconds <= 0:
        return max(settle, 12.0)
    return settle


def estimate_calibration_duration_seconds(
    s: Settings,
    kind: CalibrationKind,
    *,
    count: int,
    exposure_seconds: float,
    interval_seconds: float = 0.0,
) -> dict[str, Any]:
    """
    保守估计整次校准墙钟时间（曝光 + 读出 settle + INDI 准备 + FITS 发现）。

    用于 App 拍摄前提示；实际可能因驱动/存储略短或略长。
    """
    del kind
    n = max(1, int(count))
    exp = max(0.0, float(exposure_seconds))
    settle = effective_calibration_settle_seconds(s, exp)
    indi_overhead = 2.0
    fits_discovery = 8.0 if exp <= 0 else 5.0
    per_frame = exp + settle + indi_overhead + fits_discovery
    interval = float(interval_seconds) if interval_seconds > 0 else float(s.cal_interval_seconds)
    total = n * per_frame + max(0, n - 1) * interval
    return {
        "estimated_seconds": round(total, 1),
        "per_frame_seconds": round(per_frame, 1),
        "exposure_seconds": exp,
        "settle_seconds": round(settle, 1),
        "count": n,
        "interval_seconds": interval,
    }


def discover_frame_type_switch(device: str, host: str, port: int, *, timeout: float) -> str | None:
    """Return INDI property name (e.g. CCD_FRAME_TYPE) that lists FRAME_* elements, or None."""
    for prop in _FRAME_PROPERTY_NAMES:
        pattern = f"{device}.{prop}.*"
        r = run_getprop(host, port, pattern, timeout=timeout)
        if r.returncode != 0:
            continue
        for line in (r.stdout or "").splitlines():
            if ".FRAME_" in line or re.search(r"\.(LIGHT|BIAS|DARK|FLAT)=", line):
                return prop
    return None


def resolve_frame_element(
    device: str,
    host: str,
    port: int,
    kind: CalibrationKind,
    *,
    timeout: float,
) -> tuple[str, str]:
    """
    Return (property_name, element_name) for *kind*, e.g. (CCD_FRAME_TYPE, FRAME_BIAS).
    """
    prop = discover_frame_type_switch(device, host, port, timeout=timeout)
    if not prop:
        raise RuntimeError(
            f"{device} 未暴露 CCD_FRAME_TYPE（或 CCD_FRAME 下的 FRAME_*）；"
            f"请 indi_getprop '{device}.CCD_FRAME_TYPE.*' 确认驱动支持校准帧"
        )
    candidates = _FRAME_TYPE_CANDIDATES[kind]
    pattern = f"{device}.{prop}.*"
    r = run_getprop(host, port, pattern, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "getprop failed").strip())
    present = set()
    for line in (r.stdout or "").splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        tail = key.split(".")[-1] if key else ""
        if tail:
            present.add(tail)
    for cand in candidates:
        if cand in present:
            return prop, cand
    raise RuntimeError(
        f"{device}.{prop} 中未找到 {kind} 对应元素（尝试过 {candidates}）；"
        f"当前有：{sorted(present)}"
    )


def ccd_set_frame_type(
    device: str,
    host: str,
    port: int,
    kind: CalibrationKind,
    *,
    dry_run: bool,
    timeout: float = 15.0,
) -> list[IndiResult]:
    """Set CCD frame type switch; turn off other FRAME_* in the same property."""
    if dry_run:
        prop_guess = "CCD_FRAME_TYPE"
        elem = _FRAME_TYPE_CANDIDATES[kind][0]
        off = [f"{device}.{prop_guess}.{e}=Off" for k, els in _FRAME_TYPE_CANDIDATES.items() for e in els if k != kind]
        on = f"{device}.{prop_guess}.{elem}=On"
        steps = []
        for spec in off[:4] + [on]:
            steps.append(run_setprop(host, port, spec, dry_run=True, timeout=timeout))
        return steps

    prop, active = resolve_frame_element(device, host, port, kind, timeout=timeout)
    pattern = f"{device}.{prop}.*"
    r = run_getprop(host, port, pattern, timeout=timeout)
    elements: list[str] = []
    for line in (r.stdout or "").splitlines():
        if "=" not in line:
            continue
        key = line.split("=", 1)[0]
        tail = key.split(".")[-1]
        if tail.startswith("FRAME_") or tail in ("LIGHT", "BIAS", "DARK", "FLAT"):
            elements.append(tail)
    if not elements:
        elements = [active]
    specs: list[str] = []
    for el in elements:
        specs.append(f"{device}.{prop}.{el}={'On' if el == active else 'Off'}")
    steps: list[IndiResult] = []
    for spec in specs:
        steps.append(run_setprop(host, port, spec, dry_run=False, timeout=timeout))
    return steps


def ccd_exposure(
    device: str,
    host: str,
    port: int,
    exposure_seconds: float,
    *,
    dry_run: bool,
    settle_seconds: float,
    setprop_timeout: float = 30.0,
) -> tuple[list[IndiResult], dict[str, Any]]:
    """Like ccd_snap_exposure but allows 0 s (bias)."""
    if exposure_seconds < 0:
        raise ValueError("exposure_seconds 须 >= 0")
    spec_value = f"{device}.CCD_EXPOSURE.CCD_EXPOSURE_VALUE={exposure_seconds}"
    r_value = run_setprop(
        host,
        port,
        spec_value,
        dry_run=dry_run,
        timeout=setprop_timeout,
    )
    steps: list[IndiResult] = [r_value]
    meta: dict[str, Any] = {"waited": False, "exposure_seconds": exposure_seconds}
    if dry_run or r_value.returncode != 0:
        return steps, meta
    wait = float(exposure_seconds) + float(settle_seconds)
    if wait > 0:
        time.sleep(wait)
    meta["waited"] = True
    meta["wait_seconds"] = wait
    return steps, meta


def _snap_calibration_to_dir(
    s: Settings,
    *,
    device: str,
    exposure_seconds: float,
    cap_dir: Path,
    kind: CalibrationKind,
) -> dict[str, Any]:
    """Single calibration exposure into *cap_dir* (frame type must be set already)."""
    if not ccd_is_connected(
        device, s.indi_host, s.indi_port, timeout=max(s.indi_getprop_timeout, 2.0)
    ):
        raise RuntimeError("CCD 未连接")
    upload_steps = ccd_prepare_for_capture(
        device, s.indi_host, s.indi_port, cap_dir, dry_run=False
    )
    settle = float(s.ccd_snap_settle_seconds)
    if exposure_seconds <= 0:
        # 偏置等 0s 曝光：读出不晚于长曝光，延长等待再扫 FITS
        settle = max(settle, 12.0)
    rs, meta = ccd_exposure(
        device,
        s.indi_host,
        s.indi_port,
        exposure_seconds,
        dry_run=False,
        settle_seconds=settle,
    )
    ok = all(x.returncode == 0 for x in upload_steps + rs)
    return {
        "ok": ok,
        "action": "calibration_snap",
        "frame_kind": kind,
        "device": device,
        "exposure_seconds": exposure_seconds,
        "save_dir_hint": str(cap_dir),
        **meta,
    }


def _archive_frame(src: Path, dest_dir: Path, *, kind: CalibrationKind, index: int, exposure: float) -> Path:
    del exposure  # 曝光秒数写入 JSON 响应，不再编入文件名
    dest = dest_dir / calibration_archived_filename(kind, index)
    shutil.copy2(src, dest)
    try:
        src_r = src.resolve()
        if src_r != dest.resolve() and src_r.name.upper().startswith("IMAGE"):
            src_r.unlink(missing_ok=True)
    except OSError:
        pass
    return dest


def run_calibration_frames(
    s: Settings,
    kind: CalibrationKind,
    *,
    count: int | None = None,
    exposure_seconds: float | None = None,
    session_tag: str | None = None,
    device: str | None = None,
    execute: bool,
    interval_seconds: float = 0.0,
) -> dict[str, Any]:
    """
    Capture *count* calibration frames of *kind* into a dedicated session directory.

    Sets INDI ``CCD_FRAME_TYPE`` (or driver equivalent); 归档为 ``<kind>_NNNN.fits`` 于 ``<YYYYMMDD>/<kind>_<session>/``。
    """
    if count is not None and count < 1:
        raise ValueError("count 须 >= 1")
    n = count if count is not None else _default_count(s, kind)
    exp = exposure_seconds if exposure_seconds is not None else _default_exposure(s, kind)
    if kind in ("dark", "flat", "light") and exp <= 0 and exposure_seconds is None:
        if kind == "dark" and s.cal_dark_exposure_seconds <= 0:
            raise ValueError("暗场请指定 -s/--exposure（或设置 TELBOT_CAL_DARK_EXPOSURE_SECONDS）")
        if kind != "bias" and exp <= 0:
            raise ValueError(f"{kind} 曝光须 > 0")

    ccd = (device or s.indi_ccd_device or "").strip()
    if not ccd:
        raise RuntimeError("TELBOT_INDI_CCD_DEVICE 未设置")

    raw_tag = (session_tag or "").strip() or calibration_session_time_tag(s)
    tag = allocate_calibration_session_slug(s.ccd_save_dir, kind, raw_tag)
    save_dir = calibration_save_dir(s.ccd_save_dir, kind, tag, create=execute)
    duration_est = estimate_calibration_duration_seconds(
        s, kind, count=n, exposure_seconds=exp, interval_seconds=interval_seconds
    )

    if not execute:
        return {
            "ok": True,
            "dry_run": True,
            "action": "calibration",
            "frame_kind": kind,
            "device": ccd,
            "count": n,
            "exposure_seconds": exp,
            "session_tag": tag,
            "save_dir": str(save_dir),
            "duration_estimate": duration_est,
            "message": (
                f"干跑：将拍 {n} 张 {kind} 校准帧，曝光 {exp:g}s，保存到 {save_dir}；"
                f"预计约 {duration_est['estimated_seconds']:g} 秒。"
                "真机请加 --execute。暗场/平场请盖好镜盖或均匀光源。"
            ),
        }

    if not indi_available():
        raise RuntimeError("indi_setprop 不可用")

    if not ccd_is_connected(ccd, s.indi_host, s.indi_port, timeout=max(s.indi_getprop_timeout, 2.0)):
        raise RuntimeError("CCD 未连接；请先 telbot camera connect --execute")

    frames: list[dict[str, Any]] = []
    t = max(s.indi_getprop_timeout, 2.0)
    interval = float(interval_seconds) if interval_seconds > 0 else float(s.cal_interval_seconds)

    clear_calibration_abort_flag()
    abort_ctl = calibration_abort_controller()
    abort_ctl.start_watch()
    try:
        for i in range(1, n + 1):
            try:
                abort_ctl.check()
            except AbortRequested as e:
                completed = len(frames)
                return {
                    "ok": completed > 0,
                    "aborted": True,
                    "dry_run": False,
                    "action": "calibration",
                    "frame_kind": kind,
                    "device": ccd,
                    "count": n,
                    "exposure_seconds": exp,
                    "session_tag": tag,
                    "save_dir": str(save_dir),
                    "frames": frames,
                    "frames_completed": completed,
                    "duration_estimate": duration_est,
                    "message": (
                        f"已停止校准拍摄：完成 {completed}/{n} 张 {kind}（{e.reason}）。"
                        f" 已保存到 {save_dir}"
                    ),
                }

            ft_steps = ccd_set_frame_type(
                ccd, s.indi_host, s.indi_port, kind, dry_run=False, timeout=t
            )
            if any(r.returncode != 0 for r in ft_steps):
                return _fail(kind, tag, save_dir, i, frames, "设置 CCD_FRAME_TYPE 失败", ft_steps)

            cap_dir = save_dir
            search_dirs = exposure_capture_search_dirs(cap_dir)
            before_state = capture_before_state(search_dirs)
            snap_out = _snap_calibration_to_dir(
                s, device=ccd, exposure_seconds=exp, cap_dir=save_dir, kind=kind
            )
            if not snap_out.get("ok"):
                return _fail(kind, tag, save_dir, i, frames, f"第 {i} 帧曝光失败", snap_out)

            hint = (snap_out.get("save_dir_hint") or "").strip()
            if hint:
                cap_dir = Path(hint).expanduser().resolve()
                search_dirs = exposure_capture_search_dirs(cap_dir)
            new_fits = resolve_new_capture_fits_in_dirs(
                search_dirs,
                before_state,
                snap_grace_seconds=300.0,
                retry_attempts=24,
                retry_delay_seconds=0.5,
            )
            if new_fits is None:
                probe = fits_probe_for_dirs(search_dirs)
                return _fail(
                    kind,
                    tag,
                    save_dir,
                    i,
                    frames,
                    (
                        f"第 {i} 帧后未在 {save_dir} 发现新 FITS。"
                        f" 已扫描: {[str(p) for p in search_dirs]}；"
                        f" 当前 FITS: {probe}。"
                        " 若 FITS 在上一级 YYYYMMDD 目录，请确认 Ekos Upload 目录与 Telbot 会话目录一致。"
                    ),
                    {"snap": snap_out, "fits_probe": probe, "search_dirs": [str(p) for p in search_dirs]},
                )
            archived = _archive_frame(new_fits, save_dir, kind=kind, index=i, exposure=exp)
            frames.append(
                {
                    "index": i,
                    "exposure_seconds": exp,
                    "driver_path": str(new_fits),
                    "archived_path": str(archived),
                }
            )
            if interval > 0 and i < n:
                time.sleep(interval)
    finally:
        abort_ctl.stop_watch()
        clear_calibration_abort_flag()

    return {
        "ok": True,
        "dry_run": False,
        "action": "calibration",
        "frame_kind": kind,
        "device": ccd,
        "count": n,
        "exposure_seconds": exp,
        "session_tag": tag,
        "save_dir": str(save_dir),
        "frames": frames,
        "duration_estimate": duration_est,
        "message": f"已保存 {n} 张 {kind} 校准帧到 {save_dir}",
    }


def _fail(
    kind: CalibrationKind,
    tag: str,
    save_dir: Path,
    index: int,
    frames: list[dict],
    message: str,
    detail: Any,
) -> dict[str, Any]:
    return {
        "ok": False,
        "dry_run": False,
        "action": "calibration",
        "frame_kind": kind,
        "session_tag": tag,
        "save_dir": str(save_dir),
        "frames_completed": index,
        "frames": frames,
        "message": message,
        "detail": detail,
    }
