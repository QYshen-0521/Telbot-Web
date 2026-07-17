"""Phase 2: catalog filter, moon/meridian rules, linear exposure schedule; optional weather."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from telbot.config import Settings
from telbot.dso_catalog import PlanCandidate, list_plan_candidates
from telbot.planning.coordinates import (
    apparent_altaz_star_j2000_deg,
    iter_window_sample_times,
    moon_illumination_percent,
    moon_star_separation_deg,
)
from telbot.planning.phase0_config import _norm_catalog_sources, planning_phase0_snapshot
from telbot.planning.weather import fetch_weather_for_window
from telbot.planning.window import observer_timezone, resolve_plan_window
from telbot.repo_paths import plans_dir


def parse_forbidden_azimuth_ranges(raw: str) -> list[tuple[float, float]]:
    """Comma-separated \"lo-hi\" pairs (degrees, clockwise from North)."""
    out: list[tuple[float, float]] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part or "-" not in part:
            continue
        a, b = part.split("-", 1)
        try:
            lo, hi = float(a.strip()), float(b.strip())
        except ValueError:
            continue
        out.append((lo, hi))
    return out


def azimuth_in_forbidden(az_deg: float, ranges: list[tuple[float, float]]) -> bool:
    if not ranges:
        return False
    a = az_deg % 360.0
    for lo, hi in ranges:
        lo = lo % 360.0
        hi = hi % 360.0
        if lo <= hi:
            if lo <= a <= hi:
                return True
        else:
            if a >= lo or a <= hi:
                return True
    return False


def _intervals_overlap_utc(
    a0: dt.datetime,
    a1: dt.datetime,
    b0: dt.datetime,
    b1: dt.datetime,
) -> bool:
    return a0 < b1 and a1 > b0


def schedule_exposure_blocks(
    ordered: list[dict[str, Any]],
    *,
    window_start: dt.datetime,
    window_end: dt.datetime,
    goto_buffer_s: float,
    exposure_s: float,
    meridian_buffer_minutes: float,
    strategy: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Greedy timeline: each block length = goto_buffer + exposure.
    conservative: avoid overlap with [meridian_peak ± buffer] for that target.
    advanced: no meridian avoidance (document flip manually).
    """
    blocks: list[dict[str, Any]] = []
    unscheduled: list[str] = []
    slot = dt.timedelta(seconds=max(0.0, goto_buffer_s) + max(1.0, exposure_s))
    buf = dt.timedelta(minutes=max(0.0, meridian_buffer_minutes))
    t_cursor = window_start.astimezone(dt.timezone.utc)
    w_end = window_end.astimezone(dt.timezone.utc)
    w_start = window_start.astimezone(dt.timezone.utc)
    strat = (strategy or "").strip().lower()

    for tgt in ordered:
        tid = str(tgt["catalog_id"])
        peak = tgt["meridian_peak_utc"]
        if not isinstance(peak, dt.datetime):
            raise TypeError("meridian_peak_utc must be datetime")
        peak = peak.astimezone(dt.timezone.utc)
        blk0 = max(peak - buf, w_start)
        blk1 = min(peak + buf, w_end)
        meridian_blocks = blk0 < blk1

        st = max(t_cursor, w_start)
        placed = False
        attempts = 0
        while st + slot <= w_end and attempts < 10000:
            en = st + slot
            if strat == "advanced" or not meridian_blocks or not _intervals_overlap_utc(st, en, blk0, blk1):
                blocks.append(
                    {
                        "order": len(blocks) + 1,
                        "target_id": tid,
                        "start_utc": st.isoformat(),
                        "end_utc": en.isoformat(),
                        "role": "goto_buffer_plus_exposure",
                    }
                )
                t_cursor = en
                placed = True
                break
            if st < blk0:
                st = blk0
            elif st < blk1:
                st = blk1
            else:
                st += dt.timedelta(minutes=1)
            attempts += 1

        if not placed:
            unscheduled.append(tid)

    return blocks, unscheduled


def _analyze_candidate(
    cand: PlanCandidate,
    samples: list[dt.datetime],
    s: Settings,
    forbidden: list[tuple[float, float]],
    mid_utc: dt.datetime,
    moon_illumination_pct: float,
) -> dict[str, Any] | None:
    lat, lon, el = s.latitude, s.longitude, s.elevation_m
    best_alt = -999.0
    worst_alt = 999.0
    best_t: dt.datetime | None = None
    best_az = 0.0
    for t in samples:
        alt, az = apparent_altaz_star_j2000_deg(
            cand.ra_j2000_deg,
            cand.dec_j2000_deg,
            t,
            latitude_deg=lat,
            longitude_deg=lon,
            elevation_m=el,
        )
        worst_alt = min(worst_alt, alt)
        if alt > best_alt:
            best_alt = alt
            best_t = t
            best_az = az

    if best_t is None:
        return None

    min_alt_req = float(s.plan_target_min_altitude_deg)
    if best_alt < min_alt_req:
        return None

    if forbidden and azimuth_in_forbidden(best_az, forbidden):
        return None

    vmag = cand.vmag
    faint = vmag is None or vmag > float(s.plan_faint_vmag_threshold)
    moon_downrank = False
    if s.plan_consider_moon and faint and moon_illumination_pct > float(
        s.plan_moon_illumination_max_pct_for_faint
    ):
        moon_downrank = True

    moon_sep = moon_star_separation_deg(
        cand.ra_j2000_deg,
        cand.dec_j2000_deg,
        mid_utc,
        latitude_deg=lat,
        longitude_deg=lon,
        elevation_m=el,
    )

    return {
        "catalog_id": cand.catalog_id,
        "label": cand.label,
        "kind": cand.kind,
        "ra_j2000_deg": round(cand.ra_j2000_deg, 6),
        "dec_j2000_deg": round(cand.dec_j2000_deg, 6),
        "vmag": vmag,
        "max_altitude_deg": round(best_alt, 3),
        "min_altitude_in_window_deg": round(worst_alt, 3),
        "max_altitude_azimuth_deg": round(best_az, 3),
        "meridian_peak_utc": best_t.astimezone(dt.timezone.utc),
        "moon_angular_separation_deg": round(moon_sep, 2),
        "moon_downrank": moon_downrank,
    }


def build_phase2_payload(
    s: Settings,
    from_ts: str | None,
    to_ts: str | None,
    *,
    include_weather: bool = True,
    catalog_sources: str | None = None,
    candidate_limit: int | None = None,
) -> dict[str, Any]:
    w = resolve_plan_window(s, from_ts, to_ts)
    tz = observer_timezone(s)
    src = _norm_catalog_sources(catalog_sources) if catalog_sources else _norm_catalog_sources(s.plan_catalog_sources)
    if candidate_limit is not None and candidate_limit > 0:
        lim = int(candidate_limit)
    else:
        lim = int(s.plan_candidate_limit)
    if lim <= 0:
        lim = 120

    try:
        raw_cands = list_plan_candidates(
            sources=src,
            ngc_max_vmag=float(s.plan_ngc_max_vmag),
            limit=lim,
        )
    except FileNotFoundError as e:
        raise RuntimeError(str(e)) from e

    forbidden = parse_forbidden_azimuth_ranges(s.plan_forbidden_azimuth_deg_ranges)
    step = float(s.plan_phase2_time_step_minutes)
    samples = list(iter_window_sample_times(w.start_utc, w.end_utc, step))
    if not samples:
        samples = [w.start_utc]

    mid = w.start_utc + (w.end_utc - w.start_utc) / 2
    moon_illum = moon_illumination_percent(
        mid.astimezone(dt.timezone.utc),
        latitude_deg=s.latitude,
        longitude_deg=s.longitude,
        elevation_m=s.elevation_m,
    )

    analyzed: list[dict[str, Any]] = []
    for cand in raw_cands:
        row = _analyze_candidate(
            cand,
            samples,
            s,
            forbidden,
            mid.astimezone(dt.timezone.utc),
            moon_illum,
        )
        if row is not None:
            analyzed.append(row)

    analyzed.sort(key=lambda r: (r["moon_downrank"], -float(r["max_altitude_deg"])))

    strat = (s.plan_meridian_flip_strategy or "").strip().lower()
    blocks, unsched = schedule_exposure_blocks(
        analyzed,
        window_start=w.start_utc,
        window_end=w.end_utc,
        goto_buffer_s=float(s.plan_goto_buffer_seconds),
        exposure_s=float(s.plan_default_exposure_seconds),
        meridian_buffer_minutes=float(s.plan_meridian_buffer_minutes),
        strategy=strat,
    )

    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    weather: dict[str, Any] | None = None
    if include_weather:
        weather = fetch_weather_for_window(s, w.start_utc, w.end_utc)

    advanced_note = None
    if strat == "advanced":
        advanced_note = (
            "meridian_flip_strategy=advanced：当前未自动插入翻转空窗；请在实机跨中天前后手动预留翻转与线缆安全时间。"
        )

    return {
        "schema_version": "telbot.plan_phase2.v1",
        "generated_at_utc": generated_at,
        "window": {
            "mode": w.mode,
            "start_utc": w.start_utc.isoformat(),
            "end_utc": w.end_utc.isoformat(),
            "duration_hours": round(w.duration_hours(), 4),
            "sun_altitude_threshold_deg": w.sun_altitude_threshold_deg,
            "start_local": w.start_utc.astimezone(tz).isoformat(),
            "end_local": w.end_utc.astimezone(tz).isoformat(),
        },
        "phase0_config": planning_phase0_snapshot(s),
        "moon": {
            "illumination_pct_mid_window": round(moon_illum, 2),
            "consider_moon": s.plan_consider_moon,
        },
        "weather": weather,
        "catalog": {
            "sources": src,
            "candidates_loaded": len(raw_cands),
            "after_altitude_azimuth_filters": len(analyzed),
            "forbidden_azimuth_ranges_parsed": [[a, b] for a, b in forbidden],
        },
        "targets": [
            {**r, "meridian_peak_utc": r["meridian_peak_utc"].isoformat()} for r in analyzed
        ],
        "schedule": {
            "meridian_flip_strategy": strat,
            "goto_buffer_seconds": float(s.plan_goto_buffer_seconds),
            "exposure_seconds": float(s.plan_default_exposure_seconds),
            "meridian_buffer_minutes": float(s.plan_meridian_buffer_minutes),
            "blocks": blocks,
            "unscheduled_target_ids": unsched,
            "advanced_strategy_note": advanced_note,
        },
        "plans_dir": str(plans_dir().resolve()),
    }


def save_phase2_plan_json(payload: dict[str, Any], root: Path | None = None) -> Path:
    base = root if root is not None else plans_dir()
    base.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = base / f"plan_phase2_{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
