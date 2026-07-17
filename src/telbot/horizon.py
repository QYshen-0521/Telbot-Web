"""Altitude checks before GOTO (reject targets below horizon)."""

from __future__ import annotations

from skyfield.api import Star, wgs84

from telbot.skyfield_data import get_skyfield_loader


class BelowHorizonError(ValueError):
    """Target apparent altitude is below configured minimum."""

    def __init__(self, altitude_deg: float, min_altitude_deg: float, detail: str = "") -> None:
        self.altitude_deg = altitude_deg
        self.min_altitude_deg = min_altitude_deg
        msg = (
            f"目标在地平线以下或过低：当前地平高度约 {altitude_deg:.2f}°，"
            f"最低允许 {min_altitude_deg:.2f}°。{detail}".strip()
        )
        super().__init__(msg)


def apparent_altaz_deg(
    ra_hours: float,
    dec_deg: float,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float,
) -> tuple[float, float]:
    """Apparent altitude (°) and azimuth (° from north through east) at observer now."""
    load = get_skyfield_loader()
    ts = load.timescale()
    t = ts.now()
    eph = load("de421.bsp")
    earth = eph["earth"]
    observer = earth + wgs84.latlon(latitude_deg, longitude_deg, elevation_m)
    star = Star(ra_hours=ra_hours, dec_degrees=dec_deg)
    alt, az, _dist = observer.at(t).observe(star).apparent().altaz("standard")
    return float(alt.degrees), float(az.degrees)


def apparent_altitude_deg(
    ra_hours: float,
    dec_deg: float,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float,
) -> float:
    """
    Apparent altitude (degrees) for ICRS-like RA/Dec at observer now.
    Uses same Skyfield path as star ephemeris; adequate for horizon gate.
    """
    alt, _az = apparent_altaz_deg(
        ra_hours, dec_deg, latitude_deg, longitude_deg, elevation_m
    )
    return alt


def ensure_above_horizon(
    ra_hours: float,
    dec_deg: float,
    *,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float,
    min_altitude_deg: float,
    detail: str = "",
) -> float:
    """
    Return altitude if OK; raise BelowHorizonError if alt < min_altitude_deg.
    """
    alt = apparent_altitude_deg(
        ra_hours, dec_deg, latitude_deg, longitude_deg, elevation_m
    )
    if alt < min_altitude_deg:
        raise BelowHorizonError(alt, min_altitude_deg, detail=detail)
    return alt
