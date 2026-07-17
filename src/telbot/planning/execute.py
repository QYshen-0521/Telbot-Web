"""Phase 4: execute tonight plan blocks — GOTO (J2000→JNow) + optional CCD snap."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from telbot.skyfield_data import get_skyfield_loader

from telbot.config import Settings
from telbot.ephem_body import apparent_radec_star_j2000_deg
from telbot.horizon import BelowHorizonError, ensure_above_horizon
from telbot.indi import IndiResult, park_telescope, slew_equatorial_eod
from telbot.intent_exec import execute_voice_intent
from telbot.models import VoiceIntentV1
from telbot.mount_resolve import resolve_telescope_device
from telbot.repo_paths import plans_dir
from telbot.scheduling.confirmation import validate_plan_confirmation


OnFailureMode = Literal["ask", "park", "abort"]


def resolve_latest_tonight_plan(root: Path | None = None) -> Path:
    """Most recently modified `tonight_*.json` under data/plans/."""
    base = root if root is not None else plans_dir()
    if not base.is_dir():
        raise FileNotFoundError(f"计划目录不存在：{base}")
    candidates = sorted(base.glob("tonight_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"未找到 tonight_*.json，请先运行 telbot plan tonight 生成计划。")
    return candidates[0]


def load_plan_json(path: Path) -> dict[str, Any]:
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("计划文件须为 JSON 对象")
    return data


def validate_plan_for_execution(
    payload: dict[str, Any],
    *,
    will_execute: bool,
    force: bool,
) -> None:
    """真机执行前要求 tonight schema + confirmation，除非 --force。"""
    validate_plan_confirmation(
        payload,
        expected_schema_prefix="telbot.plan_tonight",
        will_execute=will_execute,
        force=force,
    )


def _targets_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for t in payload.get("targets") or []:
        cid = t.get("catalog_id")
        if cid is not None:
            out[str(cid)] = t
    return out


def _step_dict(r: IndiResult) -> dict[str, Any]:
    return {"stdout": r.stdout, "stderr": r.stderr, "code": r.returncode}


def _goto_from_j2000(
    s: Settings,
    target: dict[str, Any],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """J2000 from plan → apparent JNow now → EQUATORIAL_EOD + SLEW."""
    ra_deg = float(target["ra_j2000_deg"])
    dec_deg = float(target["dec_j2000_deg"])
    label = str(target.get("label", target.get("catalog_id", "")))
    ts = get_skyfield_loader().timescale()
    t = ts.now()
    pos = apparent_radec_star_j2000_deg(
        ra_deg,
        dec_deg,
        t,
        s.latitude,
        s.longitude,
        s.elevation_m,
        label,
    )
    ra_h, dec_d = pos.ra_hours, pos.dec_deg
    try:
        ensure_above_horizon(
            ra_h,
            dec_d,
            latitude_deg=s.latitude,
            longitude_deg=s.longitude,
            elevation_m=s.elevation_m,
            min_altitude_deg=s.min_altitude_deg,
            detail=f"plan execute {label}",
        )
    except BelowHorizonError as e:
        return {
            "ok": False,
            "error": str(e),
            "resolved": {"ra_hours": ra_h, "dec_deg": dec_d, "label": pos.label},
        }

    dev = resolve_telescope_device(s)
    r1, r2 = slew_equatorial_eod(
        dev,
        s.indi_host,
        s.indi_port,
        ra_h,
        dec_d,
        dry_run=dry_run,
    )
    ok = r1.returncode == 0 and r2.returncode == 0
    return {
        "ok": ok,
        "resolved": {"ra_hours": ra_h, "dec_deg": dec_d, "label": pos.label},
        "device": dev,
        "steps": [_step_dict(r1), _step_dict(r2)],
    }


def _maybe_park(s: Settings, *, dry_run: bool) -> dict[str, Any]:
    dev = resolve_telescope_device(s)
    r = park_telescope(dev, s.indi_host, s.indi_port, dry_run=dry_run)
    ok = r.returncode == 0
    return {"ok": ok, "action": "park", "device": dev, "steps": [_step_dict(r)]}


def execute_tonight_plan(
    s: Settings,
    payload: dict[str, Any],
    *,
    execute: bool,
    snap_after_goto: bool,
    on_failure: OnFailureMode = "ask",
    force: bool = False,
    confirm_continue: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """
    Run schedule blocks in order: GOTO each target (JNow at *now*), optional snap.

    on_failure:
      - abort: stop at first failed goto/snap
      - park: park mount (dry or real) then stop
      - ask: call confirm_continue(msg); if False, stop; if None, treat as stop
    """
    validate_plan_for_execution(payload, will_execute=execute, force=force)

    dry_run = not execute
    blocks = sorted(
        (payload.get("schedule") or {}).get("blocks") or [],
        key=lambda b: int(b.get("order", 0)),
    )
    by_id = _targets_by_id(payload)
    exposure = float((payload.get("schedule") or {}).get("exposure_seconds") or s.plan_default_exposure_seconds)

    results: list[dict[str, Any]] = []
    stopped_reason: str | None = None

    def _handle_failure(kind: str, tid: str = "") -> bool:
        """Return True if outer loop should break (stop entirely)."""
        nonlocal stopped_reason
        if on_failure == "abort":
            stopped_reason = kind
            return True
        if on_failure == "park":
            results.append({"order": None, "action": "on_failure_park", **_maybe_park(s, dry_run=dry_run)})
            stopped_reason = "park_after_failure"
            return True
        if on_failure == "ask":
            if kind == "missing_target":
                msg = f"计划块引用目标 {tid!r} 在 targets 中不存在。跳过并继续？"
            elif kind == "goto_failed":
                msg = f"GOTO {tid!r} 未成功。继续下一目标？"
            elif kind == "snap_failed":
                msg = f"曝光 {tid!r} 未成功。继续下一目标？"
            else:
                msg = "继续下一目标？"
            if confirm_continue is None or not confirm_continue(msg):
                stopped_reason = f"user_stop_after_{kind}"
                return True
        return False

    for b in blocks:
        tid = str(b.get("target_id", ""))
        target = by_id.get(tid)
        if target is None:
            results.append(
                {
                    "order": b.get("order"),
                    "target_id": tid,
                    "goto": {"ok": False, "error": "targets 中找不到该 catalog_id"},
                    "snap": None,
                }
            )
            if _handle_failure("missing_target", tid):
                break
            continue

        gout = _goto_from_j2000(s, target, dry_run=dry_run)
        snap_out: dict[str, Any] | None = None

        if not gout.get("ok", False):
            results.append(
                {
                    "order": b.get("order"),
                    "target_id": tid,
                    "label": target.get("label"),
                    "goto": gout,
                    "snap": None,
                }
            )
            if _handle_failure("goto_failed", tid):
                break
            continue

        if snap_after_goto:
            try:
                snap_out = execute_voice_intent(
                    s,
                    VoiceIntentV1(version=1, action="snap", exposure_seconds=exposure),
                    execute=execute,
                )
            except RuntimeError as e:
                snap_out = {"ok": False, "error": str(e)}
            if not snap_out.get("ok", False):
                results.append(
                    {
                        "order": b.get("order"),
                        "target_id": tid,
                        "label": target.get("label"),
                        "goto": gout,
                        "snap": snap_out,
                    }
                )
                if _handle_failure("snap_failed", tid):
                    break
                continue

        results.append(
            {
                "order": b.get("order"),
                "target_id": tid,
                "label": target.get("label"),
                "goto": gout,
                "snap": snap_out,
            }
        )

    if not blocks:
        stopped_reason = stopped_reason or "no_blocks"

    block_rows = [r for r in results if r.get("order") is not None and "action" not in r]
    overall_ok = stopped_reason is None and bool(block_rows) and all(
        (r.get("goto") or {}).get("ok")
        and (r.get("snap") is None or r.get("snap", {}).get("ok") is not False)
        for r in block_rows
    )

    return {
        "ok": overall_ok,
        "dry_run": dry_run,
        "stopped_reason": stopped_reason,
        "blocks_executed": len([r for r in results if r.get("order") is not None and "action" not in r]),
        "results": results,
    }
