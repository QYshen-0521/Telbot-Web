"""Phase 5: park threshold evaluation (no network)."""

from __future__ import annotations

from telbot.config import Settings
from telbot.planning.monitor import should_park_from_weather


def test_should_park_open_meteo_cloud() -> None:
    s = Settings()
    s.plan_monitor_park_mean_cloud_pct = 80.0
    w = {"provider": "open_meteo", "summary": {"mean_cloud_cover_pct": 85.0}}
    ok, reasons = should_park_from_weather(w, s)
    assert ok
    assert reasons


def test_should_not_park_below_threshold() -> None:
    s = Settings()
    w = {"provider": "open_meteo", "summary": {"mean_cloud_cover_pct": 50.0}}
    ok, _ = should_park_from_weather(w, s)
    assert not ok


def test_skipped_provider() -> None:
    s = Settings()
    ok, r = should_park_from_weather({"provider": "none", "skipped": True}, s)
    assert not ok
    assert not r
