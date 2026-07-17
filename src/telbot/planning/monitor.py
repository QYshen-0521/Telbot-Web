"""Phase 5: periodic weather check; optional Park when metrics exceed configured thresholds."""

from __future__ import annotations

import datetime as dt
from typing import Any

from telbot.config import Settings
from telbot.indi import park_telescope
from telbot.mount_resolve import resolve_telescope_device
from telbot.planning.weather import fetch_weather_for_window


def should_park_from_weather(weather: dict[str, Any], s: Settings) -> tuple[bool, list[str]]:
    """
    Return (True, reasons) if any park threshold is met.
    Supports Open-Meteo hourly summary and seven_timer approx_mean_cloud_cover_pct.
    """
    reasons: list[str] = []
    if weather.get("skipped") or weather.get("error"):
        return False, reasons

    summ = weather.get("summary") or {}
    prov = str(weather.get("provider") or "")

    cloud = summ.get("mean_cloud_cover_pct")
    if cloud is None and prov == "seven_timer":
        cloud = summ.get("approx_mean_cloud_cover_pct")

    if cloud is not None and float(cloud) >= float(s.plan_monitor_park_mean_cloud_pct):
        reasons.append(
            f"云量/近似云量 {float(cloud):.1f}% ≥ 阈值 {float(s.plan_monitor_park_mean_cloud_pct):.1f}%"
        )

    precip = summ.get("max_precipitation_probability_pct")
    if precip is not None and float(precip) >= float(s.plan_monitor_park_precip_prob_pct):
        reasons.append(
            f"降水概率峰值 {float(precip):.1f}% ≥ 阈值 {float(s.plan_monitor_park_precip_prob_pct):.1f}%"
        )

    wind = summ.get("max_wind_speed_10m_ms")
    if wind is not None and float(wind) >= float(s.plan_monitor_park_wind_ms):
        reasons.append(
            f"风速峰值 {float(wind):.1f} m/s ≥ 阈值 {float(s.plan_monitor_park_wind_ms):.1f} m/s"
        )

    return bool(reasons), reasons


def run_monitor_cycle(
    s: Settings,
    *,
    execute_park: bool,
) -> dict[str, Any]:
    """
    Fetch weather for [now, now + forecast_horizon), evaluate thresholds, optionally Park.
    """
    now = dt.datetime.now(dt.timezone.utc)
    horizon = max(0.5, float(s.plan_monitor_forecast_horizon_hours))
    end = now + dt.timedelta(hours=horizon)

    weather = fetch_weather_for_window(s, now, end)
    trigger, reasons = should_park_from_weather(weather, s)

    out: dict[str, Any] = {
        "checked_at_utc": now.isoformat(),
        "forecast_end_utc": end.isoformat(),
        "weather": weather,
        "park_triggered": trigger,
        "park_reasons": reasons,
        "park_executed": False,
        "dry_run": not execute_park,
    }

    if not trigger:
        return out

    if not execute_park:
        return out

    dev = resolve_telescope_device(s)
    r = park_telescope(dev, s.indi_host, s.indi_port, dry_run=False)
    out["park_executed"] = r.returncode == 0
    out["park_device"] = dev
    out["park_steps"] = [{"stdout": r.stdout, "stderr": r.stderr, "code": r.returncode}]
    return out
