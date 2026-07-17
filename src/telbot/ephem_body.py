from __future__ import annotations

from dataclasses import dataclass

from skyfield.api import wgs84
from skyfield.timelib import Time

from telbot.skyfield_data import get_skyfield_loader


@dataclass
class ApparentRADec:
    ra_hours: float
    dec_deg: float
    label: str


def _body(eph, name: str):
    """Resolve DE421 body; supports common aliases (e.g. jupiter -> jupiter barycenter)."""
    n = name.strip().lower()
    aliases = {
        "jupiter": "jupiter barycenter",
        "mars": "mars barycenter",
        "saturn": "saturn barycenter",
        "uranus": "uranus barycenter",
        "neptune": "neptune barycenter",
        "venus": "venus",
        "mercury": "mercury",
        "moon": "moon",
        "sun": "sun",
    }
    key = aliases.get(n, n)
    if key in eph:
        return eph[key]
    # Older Skyfield ephemeris dicts expose .keys(); SPICE kernels may not — skip fuzzy match.
    try:
        for k in eph.keys():
            if isinstance(k, str) and k.lower() == key.lower():
                return eph[k]
    except AttributeError:
        pass
    raise KeyError(f"Unknown solar system body for DE421: {name!r}. Try e.g. jupiter, mars, moon.")


def apparent_radec_jnow(
    body_name: str,
    t: Time,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float,
) -> ApparentRADec:
    """
    Topocentric apparent RA/Dec for GOTO with EQUATORIAL_EOD_COORD (JNow-style).
    Downloads de421.bsp on first run (~17MB) into ~/Telbot unless TELBOT_SKYFIELD_DATA_DIR is set.
    """
    loader = get_skyfield_loader()
    eph = loader("de421.bsp")
    earth = eph["earth"]
    body = _body(eph, body_name)
    observer = earth + wgs84.latlon(latitude_deg, longitude_deg, elevation_m)
    astrometric = observer.at(t).observe(body)
    apparent = astrometric.apparent()
    ra, dec, _dist = apparent.radec()
    label = f"{body_name} @ {t.utc_iso()}"
    return ApparentRADec(ra.hours, dec.degrees, label)


def apparent_altaz_topocentric_body(
    body_name: str,
    t: Time,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float,
) -> tuple[float, float]:
    """Standard-atmosphere apparent altitude (deg) and azimuth (deg, north=0° eastward)."""
    loader = get_skyfield_loader()
    eph = loader("de421.bsp")
    earth = eph["earth"]
    body = _body(eph, body_name)
    observer = earth + wgs84.latlon(latitude_deg, longitude_deg, elevation_m)
    apparent = observer.at(t).observe(body).apparent()
    alt, az, _dist = apparent.altaz("standard")
    return alt.degrees, az.degrees


def apparent_altaz_star_j2000_deg(
    ra_deg: float,
    dec_deg: float,
    t: Time,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float,
) -> tuple[float, float]:
    from skyfield.api import Star

    load = get_skyfield_loader()
    eph = load("de421.bsp")
    earth = eph["earth"]
    star = Star(ra_hours=ra_deg / 15.0, dec_degrees=dec_deg)
    observer = earth + wgs84.latlon(latitude_deg, longitude_deg, elevation_m)
    apparent = observer.at(t).observe(star).apparent()
    alt, az, _dist = apparent.altaz("standard")
    return alt.degrees, az.degrees


def geocentric_distance_au(body_name: str, t: Time) -> float:
    """Geocentric distance Earth center → body in AU (solar system targets only)."""
    loader = get_skyfield_loader()
    eph = loader("de421.bsp")
    earth = eph["earth"]
    body = _body(eph, body_name)
    astrometric = earth.at(t).observe(body)
    return float(astrometric.distance().au)


def apparent_radec_star_j2000_deg(
    ra_deg: float,
    dec_deg: float,
    t: Time,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float,
    label: str,
) -> ApparentRADec:
    """
    Fixed J2000 equatorial position (e.g. from star catalog) → topocentric apparent RA/Dec.
    ra_deg: 0–360, dec_deg: -90..90 (HYG convention).
    """
    from skyfield.api import Star

    load = get_skyfield_loader()
    eph = load("de421.bsp")
    earth = eph["earth"]
    star = Star(ra_hours=ra_deg / 15.0, dec_degrees=dec_deg)
    observer = earth + wgs84.latlon(latitude_deg, longitude_deg, elevation_m)
    apparent = observer.at(t).observe(star).apparent()
    ra, dec, _dist = apparent.radec()
    return ApparentRADec(ra.hours, dec.degrees, f"{label} @ {t.utc_iso()}")
