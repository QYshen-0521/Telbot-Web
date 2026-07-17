"""Planning phase 0: window resolution and config snapshot."""

from __future__ import annotations

import datetime as dt

import pytest

from telbot.config import load_settings
from telbot.planning import PlanWindow, planning_phase0_snapshot, resolve_plan_window
from telbot.planning.phase0_config import validate_planning_settings
from telbot.planning.window import compute_auto_night_window_utc


def test_resolve_explicit_window() -> None:
    s = load_settings()
    w = resolve_plan_window(
        s,
        "2026-03-28T10:00:00+00:00",
        "2026-03-28T16:00:00+00:00",
    )
    assert isinstance(w, PlanWindow)
    assert w.mode == "explicit"
    assert w.sun_altitude_threshold_deg is None
    assert w.start_utc.hour == 10
    assert w.duration_hours() == 6.0


def test_resolve_explicit_requires_both() -> None:
    s = load_settings()
    with pytest.raises(ValueError, match="同时"):
        resolve_plan_window(s, "2026-03-28T10:00:00+00:00", None)
    with pytest.raises(ValueError, match="同时"):
        resolve_plan_window(s, None, "2026-03-28T16:00:00+00:00")


def test_resolve_explicit_requires_timezone() -> None:
    s = load_settings()
    with pytest.raises(ValueError, match="时区"):
        resolve_plan_window(s, "2026-03-28T10:00:00", "2026-03-28T16:00:00+00:00")


def test_resolve_explicit_end_after_start() -> None:
    s = load_settings()
    with pytest.raises(ValueError, match="晚于"):
        resolve_plan_window(
            s,
            "2026-03-28T16:00:00+00:00",
            "2026-03-28T10:00:00+00:00",
        )


def test_validate_planning_settings_bad_meridian() -> None:
    s = load_settings().model_copy(update={"plan_meridian_flip_strategy": "flip_now"})
    with pytest.raises(ValueError, match="MERIDIAN"):
        validate_planning_settings(s)


def test_validate_planning_settings_bad_weather() -> None:
    s = load_settings().model_copy(update={"plan_weather_provider": "accuweather"})
    with pytest.raises(ValueError, match="WEATHER"):
        validate_planning_settings(s)


def test_planning_phase0_snapshot_keys() -> None:
    s = load_settings()
    snap = planning_phase0_snapshot(s)
    assert "observer" in snap and "night" in snap
    assert "phase5_monitor" in snap
    assert "weather" in snap and snap["weather"]["provider"] in (
        "open_meteo",
        "seven_timer",
        "qweather",
        "none",
    )


def test_auto_night_window_summer_afternoon_shanghai() -> None:
    """Mid-latitude summer afternoon UTC → next evening night start and following dawn."""
    now = dt.datetime(2026, 6, 15, 6, 0, 0, tzinfo=dt.timezone.utc)
    start, end = compute_auto_night_window_utc(
        latitude_deg=31.2,
        longitude_deg=121.5,
        elevation_m=10.0,
        threshold_deg=-6.0,
        step_minutes=5.0,
        max_search_days=4.0,
        now_utc=now,
    )
    assert start.tzinfo == dt.timezone.utc
    assert end.tzinfo == dt.timezone.utc
    assert start > now
    assert end > start
    assert (end - start).total_seconds() > 3600
