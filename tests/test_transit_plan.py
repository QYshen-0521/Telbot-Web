"""Transit plan window/steps generation."""

from __future__ import annotations

import datetime as dt

import pytest

from telbot.config import Settings
from telbot.planning.transit_pending import (
    resolve_event_from_pending,
    save_pending_transits,
)
from telbot.planning.transit_plan import (
    SCHEMA_VERSION,
    build_transit_plan,
    compute_observation_window,
    parse_event_utc_label,
)


def _sample_event(**overrides: object) -> dict:
    base = {
        "planet": "WASP-12 b",
        "host": "WASP-12",
        "host_vmag": 11.7,
        "transit_depth_pct": 1.5,
        "transit_duration_h": 2.5,
        "ingress_utc": "2026-06-01 18:00 UTC",
        "egress_utc": "2026-06-01 20:30 UTC",
        "mid_utc": "2026-06-01 19:15 UTC",
        "ra_deg": 97.65,
        "dec_deg": 29.81,
        "fully_observable": True,
        "difficulty_label": "中等",
    }
    base.update(overrides)
    return base


def test_parse_event_utc_label() -> None:
    d = parse_event_utc_label("2026-06-01 18:00 UTC")
    assert d.hour == 18
    assert d.tzinfo == dt.timezone.utc


def test_compute_observation_window_baseline() -> None:
    s = Settings(transit_baseline_h=1.0, transit_baseline_k=1.5)
    ev = _sample_event()
    start, end, baseline_h, warnings = compute_observation_window(ev, s)
    assert baseline_h == max(1.0, 1.5 * 2.5)
    ingress = parse_event_utc_label(ev["ingress_utc"])
    assert start == ingress - dt.timedelta(hours=baseline_h)
    assert not any("fully_observable" in w for w in warnings)


def test_compute_observation_window_warns_partial() -> None:
    s = Settings()
    _, _, _, warnings = compute_observation_window(_sample_event(fully_observable=False), s)
    assert any("fully_observable" in w for w in warnings)


def test_resolve_event_from_pending_index() -> None:
    events = [_sample_event(planet="A b"), _sample_event(planet="B b")]
    ev = resolve_event_from_pending({"events": events}, event_index=2)
    assert ev["planet"] == "B b"


def test_build_transit_plan_dry(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(
        indi_device="Test Mount",
        indi_ccd_device="Test CCD",
        indi_cfw_device="Test CFW",
        indi_focuser_device="Test Focuser",
        latitude=31.2,
        longitude=121.5,
        transit_exposure_seconds=0.0,
        expose_loop_overhead_seconds=5.0,
        transit_include_ingress_precheck=True,
    )
    event = _sample_event()
    monkeypatch.setattr(
        "telbot.planning.transit_plan.resolve_transit_event",
        lambda *_a, **_k: event,
    )
    night_start = parse_event_utc_label("2026-06-01 12:00 UTC")
    night_end = parse_event_utc_label("2026-06-02 06:00 UTC")

    class FakeWindow:
        start_utc = night_start
        end_utc = night_end
        mode = "auto"

    monkeypatch.setattr(
        "telbot.planning.transit_plan.resolve_plan_window",
        lambda *_a, **_k: FakeWindow(),
    )
    monkeypatch.setattr(
        "telbot.planning.transit_plan._jnow_at",
        lambda *_a, **_k: (6.5, 29.8),
    )

    payload = build_transit_plan(s, planet="WASP-12 b")
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["target"]["planet"] == "WASP-12 b"
    assert payload["confirmation"] is None
    actions = [st["action"] for st in payload["steps"]]
    assert "mount_connect" in actions
    assert "ingress_precheck" in actions
    assert "expose_loop" in actions
    assert "mount_park" in actions
    loop = next(st for st in payload["steps"] if st["action"] == "expose_loop")
    assert loop["kind"] == "interval"
    inst = payload["instrument_profile"]
    assert inst["etc"]["method"] == "photon_noise_depth_snr_v1"
    assert loop["exposure_seconds"] == inst["exposure_seconds"]
    assert loop["cadence_seconds"] == inst["cadence_seconds"]


def test_build_transit_plan_without_connected_devices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Planning must not require INDI or USB; empty device keys use Settings defaults."""
    s = Settings(
        indi_device="",
        indi_ccd_device="",
        indi_cfw_device="",
        indi_focuser_device="",
        latitude=31.2,
        longitude=121.5,
        transit_exposure_seconds=30.0,
        transit_include_ingress_precheck=False,
    )
    event = _sample_event()
    monkeypatch.setattr(
        "telbot.planning.transit_plan.resolve_transit_event",
        lambda *_a, **_k: event,
    )
    night_start = parse_event_utc_label("2026-06-01 12:00 UTC")
    night_end = parse_event_utc_label("2026-06-02 06:00 UTC")

    class FakeWindow:
        start_utc = night_start
        end_utc = night_end
        mode = "auto"

    monkeypatch.setattr(
        "telbot.planning.transit_plan.resolve_plan_window",
        lambda *_a, **_k: FakeWindow(),
    )
    monkeypatch.setattr(
        "telbot.planning.transit_plan._jnow_at",
        lambda *_a, **_k: (6.5, 29.8),
    )
    payload = build_transit_plan(s, planet="WASP-12 b")
    inst = payload["instrument_profile"]
    assert inst["mount_device"] == "Losmandy Gemini"
    assert inst["ccd_device"] == "ZWO CCD ASI294MC Pro"
    assert inst.get("planning_mode") == "env_defaults"
    assert any("不检测" in w for w in payload.get("warnings") or [])


def test_save_pending_roundtrip(tmp_path) -> None:
    from telbot.planning.transit_pending import load_pending_transits

    report = {"events": [_sample_event()], "count": 1, "window": {}}
    save_pending_transits(report, root=tmp_path)
    loaded = load_pending_transits(root=tmp_path, ttl_hours=999)
    assert loaded is not None
    assert len(loaded["events"]) == 1
