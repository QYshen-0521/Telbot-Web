"""Build telbot.plan_transit.v1 observing plans for exoplanet transits."""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Literal

from rich.console import Console
from rich.table import Table

from telbot.config import (
    Settings,
    effective_indi_ccd_device_name,
    effective_indi_cfw_device_name,
    effective_indi_device_name,
    effective_indi_focuser_device_name,
)
from telbot.ephem_body import apparent_radec_star_j2000_deg
from telbot.exoplanet_transits import build_exoplanet_transit_report
from telbot.fits_session import slugify_session_tag
from telbot.planning.transit_pending import (
    load_pending_transits,
    resolve_event_from_pending,
    save_pending_transits,
)
from telbot.repo_paths import plans_dir
from telbot.planning.window import observer_timezone, resolve_plan_window
from telbot.planning.transit_etc import compute_transit_exposure
from telbot.skyfield_data import get_skyfield_loader

SCHEMA_VERSION = "telbot.plan_transit.v1"


def parse_event_utc_label(label: str) -> dt.datetime:
    """Parse event time from scan output (``YYYY-MM-DD HH:MM UTC``) or ISO 8601."""
    s = label.strip()
    if not s:
        raise ValueError("事件时间为空")
    if s.endswith(" UTC"):
        core = s[: -len(" UTC")].strip()
        d = dt.datetime.strptime(core, "%Y-%m-%d %H:%M")
        return d.replace(tzinfo=dt.timezone.utc)
    from telbot.scheduling.time_util import parse_utc_iso

    return parse_utc_iso(s.replace("Z", "+00:00") if s.endswith("Z") else s)


def compute_observation_window(
    event: dict[str, Any],
    s: Settings,
    *,
    night_start: dt.datetime | None = None,
    night_end: dt.datetime | None = None,
) -> tuple[dt.datetime, dt.datetime, float, list[str]]:
    """Ingress/egress ± baseline, optionally clipped to night window."""
    ingress = parse_event_utc_label(str(event["ingress_utc"]))
    egress = parse_event_utc_label(str(event["egress_utc"]))
    t14 = float(event.get("transit_duration_h") or 0.0)
    baseline_h = max(float(s.transit_baseline_h), float(s.transit_baseline_k) * t14)
    t_start = ingress - dt.timedelta(hours=baseline_h)
    t_end = egress + dt.timedelta(hours=baseline_h)

    warnings: list[str] = []
    if not event.get("fully_observable"):
        warnings.append("fully_observable=false: 凌食末段可能低于地平")
    if t14 <= 0:
        warnings.append("transit_duration_h 缺失或为 0，baseline 仅用 TELBOT_TRANSIT_BASELINE_H")

    if night_start is not None and night_end is not None:
        ns = night_start.astimezone(dt.timezone.utc)
        ne = night_end.astimezone(dt.timezone.utc)
        if t_end <= ns or t_start >= ne:
            raise ValueError(
                "凌食观测窗与今夜天文夜窗无交集；请换目标或调整 --from/--to。"
            )
        clipped_start = max(t_start, ns)
        clipped_end = min(t_end, ne)
        if clipped_start > t_start or clipped_end < t_end:
            warnings.append("观测窗已与天文夜窗求交（部分 baseline 被裁切）")
        t_start, t_end = clipped_start, clipped_end

    return t_start, t_end, baseline_h, warnings


def _jnow_at(
    ra_deg: float,
    dec_deg: float,
    when_utc: dt.datetime,
    s: Settings,
    label: str,
) -> tuple[float, float]:
    ts = get_skyfield_loader().timescale()
    t = ts.from_datetime(when_utc.astimezone(dt.timezone.utc))
    pos = apparent_radec_star_j2000_deg(
        ra_deg,
        dec_deg,
        t,
        s.latitude,
        s.longitude,
        s.elevation_m,
        label,
    )
    return pos.ra_hours, pos.dec_deg


def _resolve_exposure_and_cadence(
    s: Settings,
    event: dict[str, Any],
    *,
    exposure_override: float | None,
) -> tuple[float, float, dict[str, Any], list[str]]:
    """
    Return (exposure_seconds, cadence_seconds, etc_block, extra_warnings).

    ``exposure_override`` from CLI; else ETC. Env ``TELBOT_TRANSIT_EXPOSURE_SECONDS>0`` also overrides.
    """
    warnings: list[str] = []
    manual_env = float(s.transit_exposure_seconds) > 0

    if exposure_override is not None:
        exp = float(exposure_override)
        if exp <= 0:
            raise ValueError("exposure_seconds 须 > 0")
        cadence = exp + max(0.0, float(s.expose_loop_overhead_seconds))
        etc_block: dict[str, Any] = {
            "schema_version": "telbot.transit_etc.v1",
            "exposure_seconds": exp,
            "cadence_seconds": cadence,
            "method": "manual_cli_override",
            "warnings": [],
        }
        warnings.append("曝光由 CLI --exposure 手动指定，未运行 ETC")
        return exp, cadence, etc_block, warnings

    if manual_env:
        exp = float(s.transit_exposure_seconds)
        cadence = exp + max(0.0, float(s.expose_loop_overhead_seconds))
        etc_block = {
            "schema_version": "telbot.transit_etc.v1",
            "exposure_seconds": exp,
            "cadence_seconds": cadence,
            "method": "manual_env_override",
            "warnings": [],
        }
        warnings.append("曝光由 TELBOT_TRANSIT_EXPOSURE_SECONDS 手动指定，未运行 ETC")
        return exp, cadence, etc_block, warnings

    etc_out = compute_transit_exposure(s, event, planning_only=True)
    exp = float(etc_out["exposure_seconds"])
    cadence = float(etc_out["cadence_seconds"])
    return exp, cadence, etc_out, warnings + list(etc_out.get("warnings") or [])


def _iso_utc(d: dt.datetime) -> str:
    return d.astimezone(dt.timezone.utc).isoformat()


def _offset_step(
    window_start: dt.datetime,
    minutes_before: float,
    action: str,
    **extra: Any,
) -> dict[str, Any]:
    at = window_start - dt.timedelta(minutes=minutes_before)
    return {"kind": "absolute", "at_utc": _iso_utc(at), "action": action, **extra}


def _step_at_ingress_offset(
    ingress_utc: dt.datetime,
    minutes_before: float,
    action: str,
    **extra: Any,
) -> dict[str, Any]:
    at = ingress_utc - dt.timedelta(minutes=minutes_before)
    return {"kind": "absolute", "at_utc": _iso_utc(at), "action": action, **extra}


def build_transit_steps(
    s: Settings,
    event: dict[str, Any],
    *,
    window_start: dt.datetime,
    window_end: dt.datetime,
    exposure_seconds: float,
    cadence_seconds: float,
    filter_name: str,
) -> list[dict[str, Any]]:
    """Setup → science expose_loop → teardown."""
    steps: list[dict[str, Any]] = []
    ra_deg = float(event["ra_deg"])
    dec_deg = float(event["dec_deg"])
    planet = str(event.get("planet", "target"))
    goto_at = window_start - dt.timedelta(minutes=s.transit_setup_goto_min)
    ra_h, dec_d = _jnow_at(ra_deg, dec_deg, goto_at, s, planet)

    steps.append(_offset_step(window_start, s.transit_setup_connect_min, "mount_connect"))
    steps.append(_offset_step(window_start, s.transit_setup_unpark_min, "mount_unpark"))
    steps.append(
        {
            "kind": "absolute",
            "at_utc": _iso_utc(goto_at),
            "action": "mount_goto",
            "ra_hours": round(ra_h, 6),
            "dec_deg": round(dec_d, 6),
            "frame": "JNOW",
            "label": planet,
        }
    )

    cfw = (s.indi_cfw_device or "").strip()
    if cfw and filter_name:
        steps.append(
            _offset_step(
                window_start,
                s.transit_setup_cfw_min,
                "cfw_goto",
                slot_name=filter_name,
            )
        )

    focuser = (s.indi_focuser_device or "").strip()
    if focuser and s.transit_include_autofocus:
        steps.append(
            _offset_step(
                window_start,
                s.transit_setup_autofocus_min,
                "focuser_autofocus",
                strategy="startup",
            )
        )

    if s.transit_include_platesolve:
        steps.append(
            _offset_step(
                window_start,
                s.transit_setup_platesolve_min,
                "platesolve_check",
                exposure_seconds=exposure_seconds,
            )
        )

    ingress_utc = parse_event_utc_label(str(event["ingress_utc"]))
    if s.transit_include_ingress_precheck:
        pre_exp = (
            float(s.transit_ingress_precheck_exposure_seconds)
            if s.transit_ingress_precheck_exposure_seconds > 0
            else exposure_seconds
        )
        steps.append(
            _step_at_ingress_offset(
                ingress_utc,
                s.transit_ingress_precheck_min,
                "ingress_precheck",
                planet=planet,
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                ingress_utc_label=str(event["ingress_utc"]),
                exposure_seconds=pre_exp,
            )
        )

    session_tag = slugify_session_tag(f"transit_{planet.replace(' ', '_')}")
    steps.append(
        {
            "kind": "interval",
            "from_utc": _iso_utc(window_start),
            "until_utc": _iso_utc(window_end),
            "action": "expose_loop",
            "exposure_seconds": exposure_seconds,
            "cadence_seconds": cadence_seconds,
            "filter": filter_name,
            "session_tag": session_tag,
        }
    )

    park_at = window_end + dt.timedelta(minutes=2.0)
    steps.append(
        {
            "kind": "absolute",
            "at_utc": _iso_utc(park_at),
            "action": "mount_park",
        }
    )
    return steps


def resolve_transit_event(
    s: Settings,
    *,
    planet: str | None = None,
    event_index: int | None = None,
    refresh_if_missing: bool = True,
) -> dict[str, Any]:
    """Resolve event from pending file or rescan + match planet name / index."""
    pending = load_pending_transits(ttl_hours=s.transit_pending_ttl_hours)
    if pending and not pending.get("_expired"):
        try:
            return resolve_event_from_pending(pending, planet=planet, event_index=event_index)
        except ValueError:
            if event_index is not None and not planet:
                raise
            if not refresh_if_missing:
                raise

    if event_index is not None and refresh_if_missing:
        report = build_exoplanet_transit_report(s)
        save_pending_transits(report)
        return resolve_event_from_pending(
            {"events": report.get("events") or []},
            event_index=event_index,
        )

    if not planet:
        raise ValueError(
            "无 pending 列表或已过期；请带 --planet 全名，或先 telbot plan transits。"
        )
    if not refresh_if_missing:
        raise ValueError(f"pending 中无 {planet!r}，且未允许重新扫描。")

    report = build_exoplanet_transit_report(s)
    save_pending_transits(report)
    events = report.get("events") or []
    key = planet.strip().lower()
    for ev in events:
        if str(ev.get("planet", "")).lower() == key or key in str(ev.get("planet", "")).lower():
            return ev
    raise ValueError(f"今晚观测窗内未找到 {planet!r} 的凌星事件。")


def _planning_instrument_warnings(s: Settings) -> list[str]:
    """Notes when plan build uses .env defaults without requiring connected hardware."""
    warnings: list[str] = []
    if not (s.indi_device or "").strip():
        warnings.append(
            f"TELBOT_INDI_DEVICE 未设置，计划使用默认赤道仪名 {effective_indi_device_name(s)!r}（仅规划，勿求 INDI 已连接）"
        )
    if not (s.indi_ccd_device or "").strip():
        warnings.append(
            f"TELBOT_INDI_CCD_DEVICE 未设置，计划使用默认相机名 {effective_indi_ccd_device_name(s)!r}（仅规划）"
        )
    warnings.append(
        "凌星计划生成不检测 Pi/INDI 连接；ETC 使用 .env 与 instrument_etc_catalog，真机执行前请核对设备名。"
    )
    return warnings


def build_transit_plan(
    s: Settings,
    *,
    planet: str | None = None,
    event_index: int | None = None,
    filter_name: str | None = None,
    exposure_seconds: float | None = None,
) -> dict[str, Any]:
    """Build full telbot.plan_transit.v1 payload (confirmation=null).

    Does not require indiserver or hardware; device names and ETC come from ``.env``
    (with built-in defaults when mount/CCD keys are empty).
    """
    mount = effective_indi_device_name(s)
    ccd = effective_indi_ccd_device_name(s)
    cfw_dev = effective_indi_cfw_device_name(s)
    focuser_dev = effective_indi_focuser_device_name(s)

    event = resolve_transit_event(s, planet=planet, event_index=event_index)
    night = resolve_plan_window(s, None, None)
    w_start, w_end, baseline_h, warnings = compute_observation_window(
        event,
        s,
        night_start=night.start_utc,
        night_end=night.end_utc,
    )

    exp, cadence, etc_block, exp_warnings = _resolve_exposure_and_cadence(
        s, event, exposure_override=exposure_seconds
    )
    filt = (filter_name or s.transit_default_filter or "Clear").strip()

    instrument_warnings: list[str] = _planning_instrument_warnings(s)
    if not cfw_dev:
        instrument_warnings.append("未配置滤镜轮（TELBOT_INDI_CFW_DEVICE 为空）：计划将省略 cfw_goto")
    if not focuser_dev:
        instrument_warnings.append("未配置电调（TELBOT_INDI_FOCUSER_DEVICE 为空）：计划将省略自动对焦")

    steps = build_transit_steps(
        s,
        event,
        window_start=w_start,
        window_end=w_end,
        exposure_seconds=exp,
        cadence_seconds=cadence,
        filter_name=filt if cfw_dev else "",
    )

    span_h = (w_end - w_start).total_seconds() / 3600.0
    est_frames = max(0, int((w_end - w_start).total_seconds() // cadence))

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "observer": {
            "latitude": s.latitude,
            "longitude": s.longitude,
            "elevation_m": s.elevation_m,
        },
        "target": {
            "planet": event.get("planet"),
            "host": event.get("host"),
            "host_vmag": event.get("host_vmag"),
            "transit_depth_pct": event.get("transit_depth_pct"),
            "transit_duration_h": event.get("transit_duration_h"),
            "ra_deg": event.get("ra_deg"),
            "dec_deg": event.get("dec_deg"),
            "ingress_utc": event.get("ingress_utc"),
            "egress_utc": event.get("egress_utc"),
            "mid_utc": event.get("mid_utc"),
            "fully_observable": event.get("fully_observable"),
            "difficulty_label": event.get("difficulty_label"),
        },
        "window": {
            "start_utc": _iso_utc(w_start),
            "end_utc": _iso_utc(w_end),
            "baseline_h": round(baseline_h, 3),
            "night_window_intersection": True,
            "span_hours": round(span_h, 3),
        },
        "instrument_profile": {
            "ccd_device": ccd,
            "mount_device": mount,
            "cfw_device": cfw_dev or None,
            "focuser_device": focuser_dev or None,
            "filter": filt if cfw_dev else None,
            "exposure_seconds": exp,
            "cadence_seconds": cadence,
            "estimated_frames": est_frames,
            "etc": etc_block,
            "planning_mode": "env_defaults",
            "notes": (
                "曝光由 ETC 计算"
                if etc_block.get("method") == "photon_noise_depth_snr_v1"
                else str(etc_block.get("method", ""))
            ),
        },
        "steps": steps,
        "warnings": warnings + exp_warnings + instrument_warnings,
        "confirmation": None,
    }
    return payload


def save_transit_plan_json(payload: dict[str, Any], root: Path | None = None) -> Path:
    base = root if root is not None else plans_dir()
    base.mkdir(parents=True, exist_ok=True)
    planet = str((payload.get("target") or {}).get("planet") or "transit")
    slug = re.sub(r"[^\w\-+.]+", "_", planet).strip("_")[:40] or "transit"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = base / f"transit_{slug}_{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def resolve_latest_transit_plan(root: Path | None = None) -> Path:
    base = root if root is not None else plans_dir()
    if not base.is_dir():
        raise FileNotFoundError(f"计划目录不存在：{base}")
    candidates = sorted(
        base.glob("transit_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("未找到 transit_*.json，请先 telbot plan transit-build。")
    return candidates[0]


def format_transit_plan_summary(payload: dict[str, Any], s: Settings) -> str:
    tz = observer_timezone(s)
    target = payload.get("target") or {}
    window = payload.get("window") or {}
    inst = payload.get("instrument_profile") or {}
    planet = target.get("planet", "?")
    lines = [
        f"凌星计划：{planet}（{target.get('host', '')}）",
        f"难度：{target.get('difficulty_label', '—')}；"
        f"V={target.get('host_vmag', '—')}；"
        f"凌深 {target.get('transit_depth_pct', '—')}%",
    ]
    for key, label in (
        ("start_utc", "开始"),
        ("end_utc", "结束"),
    ):
        raw = window.get(key, "")
        try:
            d = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            loc = d.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")
            lines.append(f"{label}：{loc}（UTC {d.astimezone(dt.timezone.utc).strftime('%H:%M')}）")
        except (ValueError, TypeError):
            lines.append(f"{label}：{raw}")
    lines.append(
        f"曝光 {inst.get('exposure_seconds')}s / cadence {inst.get('cadence_seconds')}s；"
        f"约 {inst.get('estimated_frames')} 帧"
    )
    etc = inst.get("etc") or {}
    if etc.get("method") == "photon_noise_depth_snr_v1":
        comp = etc.get("computed") or {}
        lines.append(
            f"ETC：{etc.get('method')}；"
            f"测光 SNR≈{comp.get('photometry_snr_at_exposure')}；"
            f"凌深等效 SNR≈{comp.get('transit_depth_snr_at_exposure')}"
        )
    elif etc.get("method"):
        lines.append(f"曝光来源：{etc.get('method')}")
    lines.append(f"步骤数：{len(payload.get('steps') or [])}")
    for w in payload.get("warnings") or []:
        lines.append(f"⚠ {w}")
    return "\n".join(lines)


def print_transit_plan_table(console: Console, payload: dict[str, Any], s: Settings) -> None:
    tz = observer_timezone(s)
    table = Table(title="凌星观测计划（telbot.plan_transit.v1）")
    table.add_column("#", justify="right", style="cyan")
    table.add_column("类型")
    table.add_column("时刻（本地）", overflow="fold")
    table.add_column("动作", style="bold")
    table.add_column("详情", overflow="fold")

    for i, step in enumerate(payload.get("steps") or [], 1):
        kind = step.get("kind", "")
        action = str(step.get("action", ""))
        detail = ""
        if action == "mount_goto":
            detail = f"RA {step.get('ra_hours')}h Dec {step.get('dec_deg')}°"
        elif action == "expose_loop":
            detail = (
                f"{step.get('exposure_seconds')}s / {step.get('cadence_seconds')}s cadence"
            )
        elif action == "cfw_goto":
            detail = str(step.get("slot_name", ""))
        elif action in ("focuser_autofocus", "platesolve_check", "ingress_precheck"):
            detail = str(step.get("strategy") or step.get("exposure_seconds") or "")
            if action == "ingress_precheck":
                detail = f"{step.get('exposure_seconds')}s 预检（ingress 前）"

        if kind == "interval":
            time_s = f"{step.get('from_utc', '')} → {step.get('until_utc', '')}"
            try:
                fr = dt.datetime.fromisoformat(str(step.get("from_utc", "")).replace("Z", "+00:00"))
                time_s = fr.astimezone(tz).strftime("%H:%M") + " → …"
            except (ValueError, TypeError):
                pass
        else:
            raw = step.get("at_utc", "")
            try:
                d = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                time_s = d.astimezone(tz).strftime("%m-%d %H:%M")
            except (ValueError, TypeError):
                time_s = str(raw)

        table.add_row(str(i), kind, time_s, action, detail)
    console.print(table)
    for w in payload.get("warnings") or []:
        console.print(f"[yellow]⚠ {w}[/yellow]")
