"""V-curve autofocus: sample focuser positions, snap CCD, pick minimum median HFR."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from telbot.autofocus.hfr import compute_median_hfr
from telbot.ccd_indi import ccd_is_connected, ccd_prepare_for_capture, ccd_snap_exposure
from telbot.ccd_paths import prepare_ccd_save_directory
from telbot.config import Settings
from telbot.focuser_indi import (
    focuser_get_absolute_position,
    focuser_get_max_position,
    focuser_move_absolute,
    focuser_wait_settled,
)
from telbot.platesolve.security import (
    fits_files_in_dir,
    max_fits_mtime_ns_in_dir,
    resolve_new_capture_fits,
)


@dataclass(frozen=True)
class FocusSample:
    position: int
    hfr: float | None
    star_count: int
    fits_path: str | None


def _sample_positions(
    center: int,
    *,
    half_range: int,
    step: int,
    max_pos: int,
    margin: int,
) -> list[int]:
    lo = max(margin, center - half_range)
    hi = min(max_pos - margin, center + half_range)
    if step <= 0 or lo >= hi:
        return [center]
    positions = list(range(lo, hi + 1, step))
    if center not in positions:
        positions.append(center)
    return sorted(set(positions))


def _best_sample(samples: list[FocusSample]) -> FocusSample | None:
    valid = [s for s in samples if s.hfr is not None]
    if not valid:
        return None
    return min(valid, key=lambda s: s.hfr)  # type: ignore[arg-type,type-var]


def _capture_fits(
    s: Settings,
    *,
    exposure_seconds: float,
    dry_run: bool,
    on_before_real: Callable[[], None] | None,
) -> tuple[Path | None, dict[str, Any]]:
    ccd = (s.indi_ccd_device or "").strip()
    if not ccd:
        raise RuntimeError(
            "TELBOT_INDI_CCD_DEVICE 未设置，自动对焦需要 CCD 拍照测 HFR。"
        )
    cap_dir = prepare_ccd_save_directory(s.ccd_save_dir, dry_run=dry_run)
    if not dry_run and not os.access(cap_dir, os.W_OK):
        raise RuntimeError(f"CCD 保存目录不可写：{cap_dir}")
    before_paths = fits_files_in_dir(cap_dir) if not dry_run else frozenset()
    since_ns = max_fits_mtime_ns_in_dir(cap_dir) if not dry_run else 0
    upload_steps = ccd_prepare_for_capture(
        ccd,
        s.indi_host,
        s.indi_port,
        cap_dir,
        dry_run=dry_run,
        on_before_real=on_before_real,
    )
    rs, meta = ccd_snap_exposure(
        ccd,
        s.indi_host,
        s.indi_port,
        exposure_seconds,
        dry_run=dry_run,
        settle_seconds=s.ccd_snap_settle_seconds,
        on_before_real=on_before_real,
    )
    ok = all(x.returncode == 0 for x in upload_steps + rs)
    meta = {**meta, "save_dir": str(cap_dir), "ccd_device": ccd, "ok": ok}
    if dry_run or not ok:
        return None, meta
    fits = resolve_new_capture_fits(cap_dir, since_ns, before_paths)
    if fits is None:
        raise RuntimeError(f"曝光后未在 {cap_dir} 找到新 FITS 文件")
    return fits, meta


def _measure_at_position(
    s: Settings,
    foc: str,
    position: int,
    *,
    exposure_seconds: float,
    dry_run: bool,
    on_before_real: Callable[[], None] | None,
) -> FocusSample:
    if not dry_run:
        r = focuser_move_absolute(
            foc,
            s.indi_host,
            s.indi_port,
            position,
            dry_run=False,
            on_before_real=on_before_real,
        )
        if r.returncode != 0:
            raise RuntimeError(f"电调移动到 {position} 失败")
        focuser_wait_settled(
            foc,
            s.indi_host,
            s.indi_port,
            timeout=s.autofocus_focuser_timeout_s,
            poll_interval=s.autofocus_focuser_poll_s,
            getprop_timeout=s.indi_getprop_timeout,
        )
        time.sleep(max(0.0, s.autofocus_settle_seconds))
    fits, _meta = _capture_fits(
        s,
        exposure_seconds=exposure_seconds,
        dry_run=dry_run,
        on_before_real=on_before_real,
    )
    if dry_run or fits is None:
        return FocusSample(position=position, hfr=None, star_count=0, fits_path=None)
    hfr, stars = compute_median_hfr(fits)
    return FocusSample(
        position=position,
        hfr=hfr,
        star_count=stars,
        fits_path=str(fits),
    )


def _scan_pass(
    s: Settings,
    foc: str,
    center: int,
    *,
    half_range: int,
    step: int,
    max_pos: int,
    exposure_seconds: float,
    dry_run: bool,
    on_before_real: Callable[[], None] | None,
) -> list[FocusSample]:
    positions = _sample_positions(
        center,
        half_range=half_range,
        step=step,
        max_pos=max_pos,
        margin=s.autofocus_margin_steps,
    )
    samples: list[FocusSample] = []
    for pos in positions:
        samples.append(
            _measure_at_position(
                s,
                foc,
                pos,
                exposure_seconds=exposure_seconds,
                dry_run=dry_run,
                on_before_real=on_before_real,
            )
        )
    return samples


def run_autofocus(
    s: Settings,
    *,
    execute: bool,
    exposure_seconds: float | None = None,
    on_before_real: Callable[[], None] | None = None,
    ensure_focuser_connected: Callable[[], None] | None = None,
    ensure_ccd_connected: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """
    Coarse then fine V-curve scan; move focuser to minimum median HFR.

    Requires CCD + focuser INDI devices and astropy (see pyproject [autofocus]).
    """
    dry_run = not execute
    foc = (s.indi_focuser_device or "").strip()
    if not foc:
        raise RuntimeError("TELBOT_INDI_FOCUSER_DEVICE 未设置。")
    ccd = (s.indi_ccd_device or "").strip()
    if not ccd:
        raise RuntimeError("TELBOT_INDI_CCD_DEVICE 未设置，自动对焦需要相机。")

    sec = (
        exposure_seconds
        if exposure_seconds is not None
        else s.autofocus_exposure_seconds
        if s.autofocus_exposure_seconds > 0
        else s.ccd_default_exposure_seconds
    )

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "action": "focuser_autofocus",
            "focuser_device": foc,
            "ccd_device": ccd,
            "exposure_seconds": sec,
            "message": (
                f"干跑：将对 {foc!r} 做 V 曲线扫描（粗步长 {s.autofocus_coarse_step}、"
                f"细步长 {s.autofocus_fine_step}，范围 ±{s.autofocus_half_range_steps}），"
                f"每点用 {ccd!r} 曝光 {sec}s 测 HFR。真机请加 --execute。"
            ),
            "config": {
                "coarse_step": s.autofocus_coarse_step,
                "fine_step": s.autofocus_fine_step,
                "half_range_steps": s.autofocus_half_range_steps,
            },
        }

    if ensure_focuser_connected is not None:
        ensure_focuser_connected()
    if ensure_ccd_connected is not None:
        ensure_ccd_connected()
    elif not ccd_is_connected(
        ccd, s.indi_host, s.indi_port, timeout=max(s.indi_getprop_timeout, 2.0)
    ):
        raise RuntimeError(
            "CCD 未连接。请先 `telbot camera connect --execute`。"
        )

    _rc, start_pos, _ = focuser_get_absolute_position(
        foc, s.indi_host, s.indi_port, timeout=s.indi_getprop_timeout
    )
    if start_pos is None:
        raise RuntimeError("无法读取电调当前位置。")
    center = int(round(start_pos))
    _rcm, max_pos_f, _ = focuser_get_max_position(
        foc, s.indi_host, s.indi_port, timeout=s.indi_getprop_timeout
    )
    max_pos = int(max_pos_f) if max_pos_f is not None else center + s.autofocus_half_range_steps * 2

    coarse_samples = _scan_pass(
        s,
        foc,
        center,
        half_range=s.autofocus_half_range_steps,
        step=s.autofocus_coarse_step,
        max_pos=max_pos,
        exposure_seconds=sec,
        dry_run=False,
        on_before_real=on_before_real,
    )
    best_coarse = _best_sample(coarse_samples)
    if best_coarse is None or best_coarse.hfr is None:
        return {
            "ok": False,
            "dry_run": False,
            "action": "focuser_autofocus",
            "message": "粗扫未得到有效 HFR（检查对焦是否过虚、曝光是否过短/过长、是否有星点）。",
            "coarse_samples": [s.__dict__ for s in coarse_samples],
            "start_position": center,
        }

    fine_center = best_coarse.position
    fine_half = max(s.autofocus_fine_step * 2, s.autofocus_coarse_step)
    fine_samples = _scan_pass(
        s,
        foc,
        fine_center,
        half_range=fine_half,
        step=s.autofocus_fine_step,
        max_pos=max_pos,
        exposure_seconds=sec,
        dry_run=False,
        on_before_real=on_before_real,
    )
    all_samples = coarse_samples + [
        x for x in fine_samples if x.position not in {c.position for c in coarse_samples}
    ]
    best = _best_sample(all_samples)
    if best is None or best.hfr is None:
        return {
            "ok": False,
            "dry_run": False,
            "action": "focuser_autofocus",
            "message": "细扫未得到有效 HFR。",
            "samples": [s.__dict__ for s in all_samples],
            "start_position": center,
        }

    final_pos = best.position
    if final_pos != fine_center:
        focuser_move_absolute(
            foc, s.indi_host, s.indi_port, final_pos, dry_run=False, on_before_real=on_before_real
        )
        focuser_wait_settled(
            foc,
            s.indi_host,
            s.indi_port,
            timeout=s.autofocus_focuser_timeout_s,
            poll_interval=s.autofocus_focuser_poll_s,
            getprop_timeout=s.indi_getprop_timeout,
        )

    _rcf, pos_after, _ = focuser_get_absolute_position(
        foc, s.indi_host, s.indi_port, timeout=s.indi_getprop_timeout
    )

    return {
        "ok": True,
        "dry_run": False,
        "action": "focuser_autofocus",
        "focuser_device": foc,
        "ccd_device": ccd,
        "exposure_seconds": sec,
        "start_position": center,
        "best_position": final_pos,
        "position_after": int(pos_after) if pos_after is not None else final_pos,
        "best_hfr": best.hfr,
        "best_star_count": best.star_count,
        "message": (
            f"自动对焦完成：位置 {center} → {final_pos}，"
            f"HFR≈{best.hfr:.2f}px（{best.star_count} 颗星）。"
        ),
        "coarse_samples": [x.__dict__ for x in coarse_samples],
        "fine_samples": [x.__dict__ for x in fine_samples],
    }
