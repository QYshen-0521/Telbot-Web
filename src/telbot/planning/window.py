"""Resolve observing window: explicit --from/--to or automatic 'tonight' from sun altitude."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from skyfield.api import wgs84

from telbot.config import Settings
from telbot.skyfield_data import get_skyfield_loader


@dataclass(frozen=True)
class PlanWindow:
    """UTC bounds for planning (stages 2+ use these for target visibility)."""

    start_utc: dt.datetime
    end_utc: dt.datetime
    mode: str  # "explicit" | "auto_night"
    sun_altitude_threshold_deg: float | None  # None if explicit override

    def duration_hours(self) -> float:
        return (self.end_utc - self.start_utc).total_seconds() / 3600.0


def observer_timezone(s: Settings) -> dt.tzinfo:
    """IANA zone from TELBOT_PLAN_TIMEZONE, else system local (for labeling only in later stages)."""
    tz_name = (s.plan_timezone or "").strip()
    if tz_name:
        return ZoneInfo(tz_name)
    return dt.datetime.now().astimezone().tzinfo


def _parse_iso_utc(z: str) -> dt.datetime:
    z = z.strip()
    d = dt.datetime.fromisoformat(z.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError(f"时间须带时区或使用 Z：{z!r}")
    return d.astimezone(dt.timezone.utc)


def resolve_plan_window(
    s: Settings,
    from_iso: str | None,
    to_iso: str | None,
) -> PlanWindow:
    """
    If both from_iso and to_iso are set, parse as ISO 8601 (timezone required).
    Otherwise compute the next interval where the Sun's apparent altitude
    (standard refraction) stays below plan_night_sun_altitude_threshold_deg, from
    either the next evening entry or from now if already dark, until the following morning.
    """
    fs = (from_iso or "").strip()
    ts = (to_iso or "").strip()
    if fs or ts:
        if not fs or not ts:
            raise ValueError("手动时间窗须同时提供 --from 与 --to（ISO 8601，须含时区）")
        start = _parse_iso_utc(fs)
        end = _parse_iso_utc(ts)
        if end <= start:
            raise ValueError("计划结束时间必须晚于开始时间")
        return PlanWindow(
            start_utc=start,
            end_utc=end,
            mode="explicit",
            sun_altitude_threshold_deg=None,
        )
    start, end = compute_auto_night_window_utc(
        latitude_deg=s.latitude,
        longitude_deg=s.longitude,
        elevation_m=s.elevation_m,
        threshold_deg=s.plan_night_sun_altitude_threshold_deg,
        step_minutes=5.0,
        max_search_days=4.0,
    )
    return PlanWindow(
        start_utc=start,
        end_utc=end,
        mode="auto_night",
        sun_altitude_threshold_deg=s.plan_night_sun_altitude_threshold_deg,
    )


def compute_auto_night_window_utc(
    *,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float,
    threshold_deg: float,
    step_minutes: float = 5.0,
    max_search_days: float = 4.0,
    now_utc: dt.datetime | None = None,
) -> tuple[dt.datetime, dt.datetime]:
    """
    Next observing night window in UTC.

    - If the Sun is already below threshold at *now*, the window starts at *now* and ends at
      the next morning when the Sun rises above the threshold (rest of tonight).
    - Otherwise, the window starts at the next evening when the Sun drops below the threshold
      and ends the following morning.

    threshold_deg: typical values: -6 (civil), -12 (nautical), -18 (astronomical).
    """
    load = get_skyfield_loader()
    eph = load("de421.bsp")
    sun = eph["sun"]
    earth = eph["earth"]
    location = earth + wgs84.latlon(latitude_deg, longitude_deg, elevation_m)
    ts = load.timescale()

    def sun_alt_deg(time) -> float:
        alt, _a, _d = location.at(time).observe(sun).apparent().altaz("standard")
        return alt.degrees

    def alt_at_utc(u: dt.datetime) -> float:
        t = ts.from_datetime(u.astimezone(dt.timezone.utc))
        return sun_alt_deg(t)

    def refine_down_cross(u_above: dt.datetime, u_below: dt.datetime) -> dt.datetime:
        """Evening: >= threshold -> < threshold."""
        lo = ts.from_datetime(u_above.astimezone(dt.timezone.utc))
        hi = ts.from_datetime(u_below.astimezone(dt.timezone.utc))
        for _ in range(50):
            mid = ts.tt_jd((lo.tt + hi.tt) / 2.0)
            if sun_alt_deg(mid) < threshold_deg:
                hi = mid
            else:
                lo = mid
        return hi.utc_datetime().replace(tzinfo=dt.timezone.utc)

    def refine_up_cross(u_below: dt.datetime, u_above: dt.datetime) -> dt.datetime:
        """Morning: < threshold -> >= threshold."""
        lo = ts.from_datetime(u_below.astimezone(dt.timezone.utc))
        hi = ts.from_datetime(u_above.astimezone(dt.timezone.utc))
        for _ in range(50):
            mid = ts.tt_jd((lo.tt + hi.tt) / 2.0)
            if sun_alt_deg(mid) < threshold_deg:
                lo = mid
            else:
                hi = mid
        return hi.utc_datetime().replace(tzinfo=dt.timezone.utc)

    now = now_utc or dt.datetime.now(dt.timezone.utc)
    step = dt.timedelta(minutes=step_minutes)
    limit = now + dt.timedelta(days=max_search_days)

    a0 = alt_at_utc(now)
    if a0 < threshold_deg:
        night_start = now
        u = now + step
        prev_alt = a0
        while u <= limit:
            a = alt_at_utc(u)
            if prev_alt < threshold_deg and a >= threshold_deg:
                night_end = refine_up_cross(u - step, u)
                return (night_start, night_end)
            prev_alt, u = a, u + step
        raise RuntimeError(
            f"已在夜窗内，但在 {max_search_days} 天内未找到太阳视高度回到 ≥ {threshold_deg}°；"
            "极地或异常请用 --from/--to"
        )

    u = now + step
    prev_alt = a0
    while u <= limit:
        a = alt_at_utc(u)
        if prev_alt >= threshold_deg and a < threshold_deg:
            night_start = refine_down_cross(u - step, u)
            u2 = night_start + step
            p2 = alt_at_utc(night_start)
            while u2 <= limit:
                a2 = alt_at_utc(u2)
                if p2 < threshold_deg and a2 >= threshold_deg:
                    night_end = refine_up_cross(u2 - step, u2)
                    return (night_start, night_end)
                p2, u2 = a2, u2 + step
            raise RuntimeError(
                f"已进入夜窗，但在 {max_search_days} 天内未找到日出（≥ {threshold_deg}°）；请用 --from/--to"
            )
        prev_alt, u = a, u + step

    raise RuntimeError(
        f"在 {max_search_days} 天内未进入夜窗（太阳视高度 < {threshold_deg}°）；"
        "极地白夜等情况请用 --from/--to"
    )
