"""Verify mount pointing via CCD snap + plate solve (optional sync)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from telbot.config import Settings
from telbot.models import VoiceIntentV1

PlatesolveAlignMode = Literal["sync", "slew"]


def verify_mount_pointing(
    s: Settings,
    *,
    execute: bool,
    exposure_seconds: float | None = None,
    align: PlatesolveAlignMode | None = None,
    intent_exec_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Snap + ASTAP plate solve; optionally SYNC/SLEW to solution.

    Dry-run: describe steps only.
    """
    sec = (
        exposure_seconds
        if exposure_seconds is not None
        else s.ccd_default_exposure_seconds
    )
    if not execute:
        msg = f"干跑：将曝光 {sec}s 并 plate solve 校验指向"
        if align:
            msg += f"，成功后 {align.upper()} 对准"
        msg += "。真机请加 --execute。"
        return {
            "ok": True,
            "dry_run": True,
            "action": "verify_pointing",
            "exposure_seconds": sec,
            "align": align,
            "message": msg,
        }

    if intent_exec_fn is None:
        from telbot.intent_exec import execute_voice_intent

        intent_exec_fn = execute_voice_intent

    ps_out = intent_exec_fn(
        s,
        VoiceIntentV1(
            version=1,
            action="platesolve",
            exposure_seconds=sec,
            platesolve_align=align,
        ),
        execute=True,
    )
    solve = ps_out.get("platesolve") or ps_out.get("solve") or ps_out
    ok = bool(ps_out.get("ok"))
    ra = None
    dec = None
    if isinstance(solve, dict):
        ra = solve.get("ra_hours") or solve.get("center_ra_hours")
        dec = solve.get("dec_deg") or solve.get("center_dec_deg")
    message = "指向校验：plate solve 成功。" if ok else "指向校验：plate solve 失败。"
    if ok and align:
        align_block = ps_out.get("align") or {}
        if align_block.get("ok"):
            message += f" 已 {align.upper()} 到解算位置。"
        elif align_block.get("skipped"):
            message += f" （{align_block.get('skipped')}）"
        else:
            message += " 对准步骤未成功。"
            ok = False
    return {
        "ok": ok,
        "dry_run": False,
        "action": "verify_pointing",
        "exposure_seconds": sec,
        "align": align,
        "platesolve": ps_out,
        "center_ra_hours": ra,
        "center_dec_deg": dec,
        "message": message,
    }
