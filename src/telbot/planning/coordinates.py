"""Topocentric alt/az and Moon helpers for observing-plan phase 2 (Skyfield + de421)."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterator

from skyfield.api import Star, wgs84

from telbot.skyfield_data import get_skyfield_loader


def apparent_altaz_star_j2000_deg(
    ra_j2000_deg: float,
    dec_j2000_deg: float,
    t_utc: dt.datetime,
    *,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float,
) -> tuple[float, float]:
    """Apparent altitude (°) and azimuth (° from North through East) for a J2000 star."""
    load = get_skyfield_loader()
    ts = load.timescale()
    t_sf = ts.from_datetime(t_utc.astimezone(dt.timezone.utc))
    eph = load("de421.bsp")
    earth = eph["earth"]
    observer = earth + wgs84.latlon(latitude_deg, longitude_deg, elevation_m)
    star = Star(ra_hours=ra_j2000_deg / 15.0, dec_degrees=dec_j2000_deg)
    alt, az, _dist = observer.at(t_sf).observe(star).apparent().altaz("standard")
    return float(alt.degrees), float(az.degrees)


def moon_illumination_percent(
    t_utc: dt.datetime,
    *,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float,
) -> float:
    """
    Approximate illuminated fraction of the Moon's disk (0–100) from Sun–Moon separation.
    """
    load = get_skyfield_loader()
    ts = load.timescale()
    t_sf = ts.from_datetime(t_utc.astimezone(dt.timezone.utc))
    eph = load("de421.bsp")
    earth = eph["earth"]
    sun = eph["sun"]
    moon = eph["moon"]
    observer = earth + wgs84.latlon(latitude_deg, longitude_deg, elevation_m)
    a = observer.at(t_sf).observe(sun).apparent()
    b = observer.at(t_sf).observe(moon).apparent()
    sep = a.separation_from(b)
    return (1.0 - math.cos(sep.radians)) / 2.0 * 100.0


def moon_star_separation_deg(
    ra_j2000_deg: float,
    dec_j2000_deg: float,
    t_utc: dt.datetime,
    *,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float,
) -> float:
    """Angular separation (°) between Moon and star (both apparent)."""
    load = get_skyfield_loader()
    ts = load.timescale()
    t_sf = ts.from_datetime(t_utc.astimezone(dt.timezone.utc))
    eph = load("de421.bsp")
    earth = eph["earth"]
    moon = eph["moon"]
    observer = earth + wgs84.latlon(latitude_deg, longitude_deg, elevation_m)
    star = Star(ra_hours=ra_j2000_deg / 15.0, dec_degrees=dec_j2000_deg)
    m_app = observer.at(t_sf).observe(moon).apparent()
    s_app = observer.at(t_sf).observe(star).apparent()
    sep = m_app.separation_from(s_app)
    return float(sep.degrees)


def iter_window_sample_times(
    start_utc: dt.datetime,
    end_utc: dt.datetime,
    step_minutes: float,
) -> Iterator[dt.datetime]:
    """Yield UTC sample times in [start_utc, end_utc] inclusive of start, exclusive of end unless empty."""
    start_utc = start_utc.astimezone(dt.timezone.utc)
    end_utc = end_utc.astimezone(dt.timezone.utc)
    if end_utc <= start_utc:
        return
    step = max(1.0, step_minutes)
    delta = dt.timedelta(minutes=step)
    cur = start_utc
    while cur < end_utc:
        yield cur
        cur += delta
