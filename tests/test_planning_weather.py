"""Planning phase 1: weather parsing and soft warnings (no real HTTP)."""

from __future__ import annotations

import datetime as dt
from unittest.mock import patch

import pytest

from telbot.config import Settings
from telbot.planning.preview import save_plan_preview_json
from telbot.planning.weather import (
    WARN_MEAN_CLOUD_COVER_PCT,
    _open_meteo_for_window,
    _soft_warnings_from_metrics,
    fetch_weather_for_window,
)


def test_soft_warnings_cloud_and_wind() -> None:
    w = _soft_warnings_from_metrics(
        mean_cloud_cover_pct=WARN_MEAN_CLOUD_COVER_PCT + 5,
        max_precipitation_probability_pct=max(40.0, WARN_MEAN_CLOUD_COVER_PCT),
        max_wind_speed_ms=16.0,
        mean_relative_humidity_pct=95.0,
    )
    assert len(w) >= 3


def test_open_meteo_filters_hours() -> None:
    fake = {
        "hourly": {
            "time": [
                "2026-06-15T10:00",
                "2026-06-15T11:00",
                "2026-06-15T12:00",
            ],
            "cloud_cover": [10.0, 80.0, 50.0],
            "precipitation_probability": [5.0, 45.0, 10.0],
            "relative_humidity_2m": [60.0, 70.0, 65.0],
            "wind_speed_10m": [3.0, 4.0, 5.0],
        }
    }

    def _fake_http(url: str, timeout: float) -> dict:  # noqa: ARG001
        return fake

    with patch("telbot.planning.weather._http_get_json", side_effect=_fake_http):
        start = dt.datetime(2026, 6, 15, 10, 30, tzinfo=dt.timezone.utc)
        end = dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.timezone.utc)
        out = _open_meteo_for_window(31.0, 121.0, start, end, timeout=5.0)

    assert out["provider"] == "open_meteo"
    assert out.get("summary")
    s = out["summary"]
    assert s["sample_hours"] == 2  # 11:00 and 12:00 buckets overlap
    assert s["mean_cloud_cover_pct"] is not None
    assert any("降水" in x for x in out["soft_warnings"])


def test_fetch_weather_none_provider() -> None:
    s = Settings()
    s.plan_weather_provider = "none"
    start = dt.datetime(2026, 6, 15, 10, 0, tzinfo=dt.timezone.utc)
    end = dt.datetime(2026, 6, 15, 14, 0, tzinfo=dt.timezone.utc)
    out = fetch_weather_for_window(s, start, end)
    assert out["provider"] == "none"
    assert out.get("skipped") is True


def test_save_plan_preview_json_writes_file(tmp_path) -> None:
    payload = {"schema_version": "telbot.plan_preview.v1", "weather": {"provider": "none"}}
    path = save_plan_preview_json(payload, root=tmp_path)
    assert path.exists()
    assert "plan_preview_" in path.name
    assert "none" in path.read_text(encoding="utf-8")


def test_qweather_skips_without_impl() -> None:
    s = Settings()
    s.plan_weather_provider = "qweather"
    s.plan_weather_api_key = "x"
    start = dt.datetime(2026, 6, 15, 10, 0, tzinfo=dt.timezone.utc)
    end = dt.datetime(2026, 6, 15, 14, 0, tzinfo=dt.timezone.utc)
    out = fetch_weather_for_window(s, start, end)
    assert out["provider"] == "qweather"
    assert out.get("skipped") is True
