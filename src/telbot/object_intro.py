"""Structured celestial-object introduction for ``describe`` intent (terminal / future HTTP→App)."""

from __future__ import annotations

import re
from typing import Any

from telbot.skyfield_data import get_skyfield_loader

from telbot.catalog import hyg_visual_magnitude_for_label
from telbot.config import Settings
from telbot.ephem_body import (
    apparent_altaz_star_j2000_deg,
    apparent_altaz_topocentric_body,
    apparent_radec_jnow,
    apparent_radec_star_j2000_deg,
    geocentric_distance_au,
)
from telbot.text_intent import normalize_ephemeris_target


def _guess_catalog_category(label: str) -> str:
    L = label.strip().upper()
    if len(L) >= 2 and L[0] == "M" and L[1].isdigit():
        return "dso"
    if "NGC" in L or _ic_in_label(L):
        return "dso"
    return "star"


def _ic_in_label(L: str) -> bool:
    return bool(re.search(r"\bIC\s*\d+", L))


def build_object_introduction(s: Settings, query: str) -> dict[str, Any]:
    """
    Resolve solar-system body, HYG star, or OpenNGC DSO; return JSON-serializable payload.
    Uses observer coordinates from Settings for apparent place.
    """
    ts = get_skyfield_loader().timescale()
    t = ts.now()
    raw_q = query.strip()
    norm = normalize_ephemeris_target(raw_q)

    intro: dict[str, Any] = {
        "query": raw_q,
        "resolved_target": norm,
        "time_utc": t.utc_iso(),
        "observer": {
            "latitude_deg": s.latitude,
            "longitude_deg": s.longitude,
            "elevation_m": s.elevation_m,
        },
    }

    try:
        pos = apparent_radec_jnow(norm, t, s.latitude, s.longitude, s.elevation_m)
        alt, az = apparent_altaz_topocentric_body(norm, t, s.latitude, s.longitude, s.elevation_m)
        dist_au = geocentric_distance_au(norm, t)
        intro["category"] = "solar_system"
        intro["label"] = norm
        intro["visual_magnitude"] = None
        intro["ra_hours_now"] = round(pos.ra_hours, 6)
        intro["dec_deg_now"] = round(pos.dec_deg, 6)
        intro["altitude_deg"] = round(alt, 2)
        intro["azimuth_deg"] = round(az, 2)
        intro["distance_au"] = round(dist_au, 8)
        intro["distance_km_geocentric_approx"] = round(dist_au * 149597870.7, 0)
    except KeyError:
        from telbot.catalog import find_star

        try:
            ra_deg, dec_deg, label = find_star(norm)
        except FileNotFoundError as e:
            raise RuntimeError(str(e)) from e

        pos = apparent_radec_star_j2000_deg(
            ra_deg, dec_deg, t, s.latitude, s.longitude, s.elevation_m, label
        )
        alt, az = apparent_altaz_star_j2000_deg(
            ra_deg, dec_deg, t, s.latitude, s.longitude, s.elevation_m
        )

        vmag_star: float | None = None
        try:
            vmag_star = hyg_visual_magnitude_for_label(label)
        except FileNotFoundError:
            pass

        vmag_dso: float | None = None
        try:
            from telbot.dso_catalog import openngc_visual_magnitude_for_query

            vmag_dso = openngc_visual_magnitude_for_query(raw_q)
            if vmag_dso is None:
                vmag_dso = openngc_visual_magnitude_for_query(norm)
            if vmag_dso is None:
                vmag_dso = openngc_visual_magnitude_for_query(label)
        except FileNotFoundError:
            pass

        vmag = vmag_star if vmag_star is not None else vmag_dso
        cat = _guess_catalog_category(label)

        intro["category"] = cat
        intro["label"] = label
        intro["ra_j2000_deg"] = round(ra_deg, 6)
        intro["dec_j2000_deg"] = round(dec_deg, 6)
        intro["visual_magnitude"] = None if vmag is None else round(float(vmag), 2)
        intro["ra_hours_now"] = round(pos.ra_hours, 6)
        intro["dec_deg_now"] = round(pos.dec_deg, 6)
        intro["altitude_deg"] = round(alt, 2)
        intro["azimuth_deg"] = round(az, 2)
        intro["distance_au"] = None

    lines = format_intro_lines(intro)
    intro["summary_lines"] = lines
    return {
        "ok": True,
        "dry_run": True,
        "action": "describe",
        "intro": intro,
    }


def format_intro_lines(intro: dict[str, Any]) -> list[str]:
    q = intro.get("query", "")
    lab = intro.get("label", "")
    cat = intro.get("category", "")
    lines = [
        f"查询：{q}",
        f"解析名称：{intro.get('resolved_target', '')}",
        f"类型：{cat}",
        f"星表/历表标签：{lab}",
        f"时刻（UTC）：{intro.get('time_utc', '')}",
    ]
    vm = intro.get("visual_magnitude")
    if vm is not None:
        lines.append(f"视星等（约）：{vm}")
    else:
        lines.append("视星等（约）：暂无或不适用")

    lines.append(
        f"当前地平坐标：高度 {intro.get('altitude_deg')}°，方位角 {intro.get('azimuth_deg')}°（北零点顺时针）"
    )
    lines.append(f"当前赤道坐标（视位置）：RA {intro.get('ra_hours_now')} h，Dec {intro.get('dec_deg_now')}°")

    if intro.get("category") != "solar_system":
        if intro.get("ra_j2000_deg") is not None:
            lines.append(
                f"历元 J2000.0：RA {intro['ra_j2000_deg']}°，Dec {intro['dec_j2000_deg']}°"
            )
    else:
        if intro.get("distance_au") is not None:
            lines.append(
                f"地心距离（约）：{intro['distance_au']} AU ≈ {intro.get('distance_km_geocentric_approx')} km"
            )

    obs = intro.get("observer") or {}
    lines.append(
        f"观测地点：纬度 {obs.get('latitude_deg')}°，经度 {obs.get('longitude_deg')}°，海拔 {obs.get('elevation_m')} m"
    )
    return lines


def print_intro_console(console: Any, payload: dict[str, Any]) -> None:
    """Rich-friendly multi-line summary for CLI."""
    intro = payload.get("intro") or {}
    for line in intro.get("summary_lines") or []:
        console.print(line)
