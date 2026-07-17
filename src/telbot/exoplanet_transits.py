"""
Tonight's observable exoplanet transit events (NASA Exoplanet Archive + astroplan).

Optional deps: ``pip install -e ".[exoplanets]"`` (astropy, astroquery, astroplan).
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Callable

from telbot.config import Settings
from telbot.planning.coordinates import (
    apparent_altaz_star_j2000_deg,
    moon_star_separation_deg,
)
from telbot.planning.window import observer_timezone, resolve_plan_window


@dataclass(frozen=True)
class PlanetEphemeris:
    """Minimal fields from NASA ``pscomppars`` for transit prediction."""

    pl_name: str
    hostname: str
    ra_deg: float
    dec_deg: float
    host_vmag: float
    tran_mid_jd: float
    orb_period_days: float
    tran_dur_hours: float
    tran_depth_pct: float | None


def _require_exoplanet_stack() -> tuple[Any, Any, Any, Any, Any]:
    try:
        import astropy.units as u
        from astropy.coordinates import SkyCoord
        from astropy.time import Time
        from astroplan import EclipsingSystem, FixedTarget, Observer, is_event_observable
        from astroplan.constraints import AltitudeConstraint, AtNightConstraint
    except ImportError as e:
        raise RuntimeError(
            "系外行星凌星查询需要可选依赖：pip install -e \".[exoplanets]\" "
            "（astropy、astroquery、astroplan）"
        ) from e
    return u, SkyCoord, Time, (EclipsingSystem, FixedTarget, Observer, is_event_observable), (
        AltitudeConstraint,
        AtNightConstraint,
    )


def compute_difficulty_score(
    *,
    host_vmag: float,
    transit_depth_pct: float | None,
    min_altitude_deg: float,
    moon_separation_deg: float,
    fully_observable: bool,
) -> float:
    """Lower score = easier to observe (heuristic)."""
    score = float(host_vmag) * 3.0
    if transit_depth_pct is not None and math.isfinite(transit_depth_pct):
        score -= min(float(transit_depth_pct), 6.0) * 2.5
    score -= min_altitude_deg * 0.12
    score += max(0.0, 50.0 - moon_separation_deg) * 0.06
    if not fully_observable:
        score += 18.0
    return round(score, 2)


def difficulty_label(score: float) -> str:
    if score < 28.0:
        return "容易"
    if score < 42.0:
        return "中等"
    return "困难"


def _is_masked(val: Any) -> bool:
    mask = getattr(val, "mask", None)
    if mask is None:
        return False
    try:
        import numpy as np

        return bool(np.any(mask))
    except Exception:
        return bool(mask)


def _float_or_none(val: Any) -> float | None:
    """Coerce NASA Archive cell (float, numpy scalar, astropy Quantity) to float."""
    if val is None:
        return None
    if _is_masked(val):
        return None
    try:
        from astropy.units import Quantity

        if isinstance(val, Quantity):
            if _is_masked(val.value):
                return None
            val = val.value
    except ImportError:
        pass
    try:
        import numpy as np

        if isinstance(val, np.generic):
            val = val.item()
        if isinstance(val, np.ma.MaskedArray):
            if np.ma.is_masked(val) or (hasattr(val, "mask") and np.any(val.mask)):
                return None
            val = val.data
    except ImportError:
        pass
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _row_get(row: Any, name: str) -> Any:
    """Table Row (``row[col]``) or SimpleNamespace (``row.col``)."""
    try:
        return row[name]
    except (KeyError, TypeError, IndexError):
        return getattr(row, name, None)


def _row_float(row: Any, *names: str) -> float | None:
    for name in names:
        val = _float_or_none(_row_get(row, name))
        if val is not None:
            return val
    return None


def _row_to_planet(row: Any) -> PlanetEphemeris | None:
    name = str(_row_get(row, "pl_name") or "").strip()
    if not name:
        return None
    # NASA PSCompPars (2021+): ra/dec; legacy queries used sy_ra/sy_dec.
    ra = _row_float(row, "ra", "sy_ra")
    dec = _row_float(row, "dec", "sy_dec")
    vmag = _row_float(row, "sy_vmag")
    t0 = _row_float(row, "pl_tranmid")
    period = _row_float(row, "pl_orbper")
    dur = _row_float(row, "pl_trandur")
    if None in (ra, dec, vmag, t0, period, dur):
        return None
    if period <= 0 or dur <= 0:
        return None
    host = str(_row_get(row, "hostname") or name.split()[0]).strip()
    depth = _float_or_none(_row_get(row, "pl_trandep"))
    return PlanetEphemeris(
        pl_name=name,
        hostname=host,
        ra_deg=ra,
        dec_deg=dec,
        host_vmag=vmag,
        tran_mid_jd=t0,
        orb_period_days=period,
        tran_dur_hours=dur,
        tran_depth_pct=depth,
    )


def fetch_transiting_planets(
    *,
    max_host_vmag: float,
    scan_limit: int,
) -> list[PlanetEphemeris]:
    """
    Query NASA Exoplanet Archive ``pscomppars`` (network required).

    Server-side ``where`` already restricts to planets with known transit
    ephemeris (``pl_tranmid``, ``pl_orbper``, ``pl_trandur``) and host
    ``sy_vmag < max_host_vmag``. Only the brightest ``scan_limit`` rows are
    parsed locally (ordered by ``sy_vmag asc``).
    """
    from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive

    where = (
        "pl_tranmid is not null and pl_orbper is not null and pl_trandur is not null "
        f"and sy_vmag is not null and sy_vmag<{max_host_vmag}"
    )
    table = NasaExoplanetArchive.query_criteria(
        table="pscomppars",
        select=(
            "pl_name,hostname,ra,dec,sy_vmag,"
            "pl_tranmid,pl_orbper,pl_trandur,pl_trandep"
        ),
        where=where,
        order="sy_vmag asc",
    )
    out: list[PlanetEphemeris] = []
    for row in table[:scan_limit]:
        p = _row_to_planet(row)
        if p is not None:
            out.append(p)
    return out


def _transit_mids_in_window(exo: Any, t_start: Any, t_end: Any, period_days: float) -> list[Any]:
    span_days = max(0.0, float(t_end.jd - t_start.jd))
    n_max = max(1, min(int(span_days / max(period_days, 0.01)) + 3, 40))
    mids = exo.next_primary_eclipse_time(t_start, n_eclipses=n_max)
    selected: list[Any] = []
    for mid in mids:
        if float(mid.jd) < float(t_start.jd):
            continue
        if float(mid.jd) > float(t_end.jd):
            break
        selected.append(mid)
    return selected


def _format_utc_local(t: Any, tz: dt.tzinfo) -> tuple[str, str]:
    d = t.to_datetime()
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    utc_s = d.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    local_s = d.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")
    return utc_s, local_s


def _configure_astropy_iers() -> None:
    """Allow stale/offline IERS tables (common on air-gapped Pi)."""
    try:
        from astropy.utils.iers import conf as iers_conf

        iers_conf.auto_max_age = None
    except Exception:
        pass


def scan_observable_transits(
    s: Settings,
    planets: list[PlanetEphemeris],
    *,
    window_start_utc: dt.datetime,
    window_end_utc: dt.datetime,
    min_altitude_deg: float,
    max_results: int,
    consider_moon: bool,
) -> list[dict[str, Any]]:
    u, SkyCoord, Time, ap, constraints_mod = _require_exoplanet_stack()
    _configure_astropy_iers()
    EclipsingSystem, FixedTarget, Observer, is_event_observable = ap
    AltitudeConstraint, AtNightConstraint = constraints_mod

    tz = observer_timezone(s)
    t_start = Time(window_start_utc, format="datetime", scale="utc")
    t_end = Time(window_end_utc, format="datetime", scale="utc")

    observer = Observer(
        latitude=s.latitude * u.deg,
        longitude=s.longitude * u.deg,
        elevation=s.elevation_m * u.m,
        name="Telbot",
    )
    constraints = [
        AltitudeConstraint(min=min_altitude_deg * u.deg),
        AtNightConstraint(),
    ]

    events: list[dict[str, Any]] = []
    for planet in planets:
        duration = planet.tran_dur_hours * u.hour
        exo = EclipsingSystem(
            primary_eclipse_time=Time(planet.tran_mid_jd, format="jd"),
            orbital_period=planet.orb_period_days * u.day,
            duration=duration,
            name=planet.pl_name,
        )
        coord = SkyCoord(planet.ra_deg * u.deg, planet.dec_deg * u.deg, frame="icrs")
        target = FixedTarget(name=planet.hostname, coord=coord)

        for mid in _transit_mids_in_window(exo, t_start, t_end, planet.orb_period_days):
            ing_egr = exo.next_primary_ingress_egress_time(mid - 0.01 * u.day, n_eclipses=1)
            if len(ing_egr) == 0:
                continue
            ingress, egress = ing_egr[0]

            mid_obs = bool(
                is_event_observable(constraints, observer, target, times=mid)[0][0]
            )
            full_obs = bool(
                is_event_observable(
                    constraints, observer, target, times_ingress_egress=ing_egr
                )[0][0]
            )
            if not mid_obs:
                continue

            mid_dt = mid.to_datetime()
            if mid_dt.tzinfo is None:
                mid_dt = mid_dt.replace(tzinfo=dt.timezone.utc)
            alt, _az = apparent_altaz_star_j2000_deg(
                planet.ra_deg,
                planet.dec_deg,
                mid_dt,
                latitude_deg=s.latitude,
                longitude_deg=s.longitude,
                elevation_m=s.elevation_m,
            )
            moon_sep = (
                moon_star_separation_deg(
                    planet.ra_deg,
                    planet.dec_deg,
                    mid_dt,
                    latitude_deg=s.latitude,
                    longitude_deg=s.longitude,
                    elevation_m=s.elevation_m,
                )
                if consider_moon
                else 90.0
            )
            score = compute_difficulty_score(
                host_vmag=planet.host_vmag,
                transit_depth_pct=planet.tran_depth_pct,
                min_altitude_deg=alt,
                moon_separation_deg=moon_sep,
                fully_observable=full_obs,
            )
            mid_utc, mid_local = _format_utc_local(mid, tz)
            ing_utc, _ = _format_utc_local(ingress, tz)
            egr_utc, _ = _format_utc_local(egress, tz)
            events.append(
                {
                    "planet": planet.pl_name,
                    "host": planet.hostname,
                    "host_vmag": round(planet.host_vmag, 2),
                    "transit_depth_pct": planet.tran_depth_pct,
                    "transit_duration_h": round(planet.tran_dur_hours, 3),
                    "mid_utc": mid_utc,
                    "mid_local": mid_local,
                    "ingress_utc": ing_utc,
                    "egress_utc": egr_utc,
                    "min_altitude_deg": round(alt, 1),
                    "moon_separation_deg": round(moon_sep, 1),
                    "mid_observable": mid_obs,
                    "fully_observable": full_obs,
                    "difficulty_score": score,
                    "difficulty_label": difficulty_label(score),
                    "ra_deg": planet.ra_deg,
                    "dec_deg": planet.dec_deg,
                }
            )

    events.sort(key=lambda e: (e["difficulty_score"], e["mid_utc"]))
    return events[:max_results]


def format_transit_events_message(events: list[dict[str, Any]], *, window_label: str) -> str:
    if not events:
        return f"{window_label}没有符合条件的系外行星凌星事件（可尝试放宽星等或检查网络/依赖）。"
    lines = [f"{window_label}共 {len(events)} 个可观测凌星事件（按难度从低到高）："]
    for i, ev in enumerate(events, 1):
        full = "全程可观测" if ev.get("fully_observable") else "仅中心可观测"
        depth = ev.get("transit_depth_pct")
        depth_s = f" 凌深{depth:.2f}%" if depth is not None else ""
        lines.append(
            f"{i}. {ev['planet']}（{ev['host']}，V={ev['host_vmag']}{depth_s}）"
            f" — {ev['mid_local']}，高度 {ev['min_altitude_deg']}°，"
            f"{full}，难度：{ev['difficulty_label']}"
        )
    return "\n".join(lines)


def build_exoplanet_transit_report(
    s: Settings,
    *,
    fetch_fn: Callable[..., list[PlanetEphemeris]] | None = None,
    from_iso: str | None = None,
    to_iso: str | None = None,
) -> dict[str, Any]:
    """Tonight (or explicit window) observable exoplanet transits."""
    window = resolve_plan_window(s, from_iso, to_iso)
    tz = observer_timezone(s)
    window_label = (
        f"观测窗 {window.start_utc.astimezone(tz).strftime('%m-%d %H:%M')}–"
        f"{window.end_utc.astimezone(tz).strftime('%m-%d %H:%M')}："
    )

    fetch = fetch_fn or fetch_transiting_planets
    planets = fetch(
        max_host_vmag=s.exoplanet_max_host_vmag,
        scan_limit=s.exoplanet_catalog_scan_limit,
    )
    events = scan_observable_transits(
        s,
        planets,
        window_start_utc=window.start_utc,
        window_end_utc=window.end_utc,
        min_altitude_deg=s.exoplanet_min_altitude_deg,
        max_results=s.exoplanet_max_results,
        consider_moon=s.exoplanet_consider_moon,
    )
    message = format_transit_events_message(events, window_label=window_label)
    report = {
        "ok": True,
        "dry_run": True,
        "action": "exoplanet_transits",
        "window": {
            "start_utc": window.start_utc.isoformat(),
            "end_utc": window.end_utc.isoformat(),
            "mode": window.mode,
        },
        "catalog_scanned": len(planets),
        "count": len(events),
        "events": events,
        "message": message,
    }
    try:
        from telbot.planning.transit_pending import save_pending_transits

        save_pending_transits(report)
    except OSError:
        pass
    return report
