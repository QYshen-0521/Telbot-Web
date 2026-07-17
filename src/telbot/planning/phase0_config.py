"""Phase-0 planning knobs (mirrors Settings) for embedding in saved plan JSON later."""

from __future__ import annotations

from typing import Any, Literal

from telbot.config import Settings

MERIDIAN_STRATEGIES = ("conservative", "advanced")
MeridianFlipStrategy = Literal["conservative", "advanced"]

WEATHER_PROVIDERS = ("open_meteo", "seven_timer", "qweather", "none")
WeatherProvider = Literal["open_meteo", "seven_timer", "qweather", "none"]

CATALOG_SOURCES = ("messier", "ngc_bright", "messier_ngc")
CatalogSourcesMode = Literal["messier", "ngc_bright", "messier_ngc"]


def _norm_meridian(s: str) -> str:
    v = (s or "").strip().lower()
    if v not in MERIDIAN_STRATEGIES:
        raise ValueError(
            f"TELBOT_PLAN_MERIDIAN_FLIP_STRATEGY 必须是 {MERIDIAN_STRATEGIES} 之一，当前为 {s!r}"
        )
    return v


def _norm_weather(s: str) -> str:
    v = (s or "").strip().lower()
    if v not in WEATHER_PROVIDERS:
        raise ValueError(
            f"TELBOT_PLAN_WEATHER_PROVIDER 必须是 {WEATHER_PROVIDERS} 之一，当前为 {s!r}"
        )
    return v


def _norm_catalog_sources(s: str) -> str:
    v = (s or "").strip().lower()
    if v not in CATALOG_SOURCES:
        raise ValueError(
            f"TELBOT_PLAN_CATALOG_SOURCES 必须是 {CATALOG_SOURCES} 之一，当前为 {s!r}"
        )
    return v


def validate_planning_settings(s: Settings) -> None:
    """Call after load_settings() if planning commands are used."""
    _norm_meridian(s.plan_meridian_flip_strategy)
    _norm_weather(s.plan_weather_provider)
    _norm_catalog_sources(s.plan_catalog_sources)


def planning_phase0_snapshot(s: Settings) -> dict[str, Any]:
    """Serializable block for plan metadata (stages 1–3)."""
    return {
        "observer": {
            "latitude_deg": s.latitude,
            "longitude_deg": s.longitude,
            "elevation_m": s.elevation_m,
        },
        "night": {
            "sun_altitude_threshold_deg": s.plan_night_sun_altitude_threshold_deg,
            "timezone_iana": (s.plan_timezone or "").strip() or None,
        },
        "targets": {
            "default_exposure_seconds": s.plan_default_exposure_seconds,
            "min_altitude_deg": s.plan_target_min_altitude_deg,
            "consider_moon": s.plan_consider_moon,
            "moon_illumination_max_pct_for_faint": s.plan_moon_illumination_max_pct_for_faint,
        },
        "meridian": {
            "flip_strategy": _norm_meridian(s.plan_meridian_flip_strategy),
            "buffer_minutes": s.plan_meridian_buffer_minutes,
        },
        "weather": {
            "provider": _norm_weather(s.plan_weather_provider),
            "query_interval_minutes": s.plan_weather_query_interval_minutes,
            "api_key_set": bool((s.plan_weather_api_key or "").strip()),
        },
        "goto_safety": {
            "min_altitude_deg": s.min_altitude_deg,
        },
        "phase2_catalog": {
            "sources": _norm_catalog_sources(s.plan_catalog_sources),
            "ngc_max_vmag": s.plan_ngc_max_vmag,
            "candidate_limit": s.plan_candidate_limit,
            "goto_buffer_seconds": s.plan_goto_buffer_seconds,
            "forbidden_azimuth_ranges_raw": (s.plan_forbidden_azimuth_deg_ranges or "").strip() or None,
            "time_step_minutes": s.plan_phase2_time_step_minutes,
            "faint_vmag_threshold": s.plan_faint_vmag_threshold,
        },
        "phase5_monitor": {
            "interval_minutes": s.plan_monitor_interval_minutes,
            "forecast_horizon_hours": s.plan_monitor_forecast_horizon_hours,
            "park_mean_cloud_pct": s.plan_monitor_park_mean_cloud_pct,
            "park_precip_prob_pct": s.plan_monitor_park_precip_prob_pct,
            "park_wind_ms": s.plan_monitor_park_wind_ms,
        },
    }
