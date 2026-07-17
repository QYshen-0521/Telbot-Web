"""Ingress pre-check (obstruction hint) for transit observing."""

from __future__ import annotations

import datetime as dt

import pytest

from telbot.config import Settings
from telbot.planning.transit_ingress_precheck import (
    SCHEMA_VERSION,
    angular_separation_arcmin,
    build_precheck_result,
    clear_last_ingress_precheck,
    get_last_ingress_precheck,
    publish_ingress_precheck_result,
    run_ingress_precheck,
)


def test_angular_separation_zero() -> None:
    assert angular_separation_arcmin(12.0, 30.0, 12.0, 30.0) == pytest.approx(0.0, abs=1e-6)


def test_build_precheck_result_user_alert_on_fail() -> None:
    check = dt.datetime(2026, 6, 1, 17, 50, tzinfo=dt.timezone.utc)
    ingress = dt.datetime(2026, 6, 1, 18, 0, tzinfo=dt.timezone.utc)
    out = build_precheck_result(
        capture_ok=False,
        reason_code="pointing_offset",
        planet="WASP-12 b",
        check_utc=check,
        ingress_utc=ingress,
        expected={"ra_hours": 6.5, "dec_deg": 29.8, "altitude_deg": 45.0},
        measured={"ra_hours": 6.6, "dec_deg": 29.9},
        offset_arcmin=12.5,
        max_offset_arcmin=8.0,
        dry_run=False,
    )
    assert out["schema_version"] == SCHEMA_VERSION
    assert out["user_alert"] is not None
    assert out["user_alert"]["action_hint"] == "reposition_telescope"
    assert out["user_alert"]["code"] == "obstruction_suspected"
    assert "遮挡" in out["user_alert"]["message"]


def test_build_precheck_result_no_alert_when_ok() -> None:
    check = dt.datetime(2026, 6, 1, 17, 50, tzinfo=dt.timezone.utc)
    ingress = dt.datetime(2026, 6, 1, 18, 0, tzinfo=dt.timezone.utc)
    out = build_precheck_result(
        capture_ok=True,
        reason_code="ok",
        planet="WASP-12 b",
        check_utc=check,
        ingress_utc=ingress,
        expected={"ra_hours": 6.5, "dec_deg": 29.8, "altitude_deg": 45.0},
        max_offset_arcmin=8.0,
        dry_run=False,
    )
    assert out["user_alert"] is None


def test_publish_and_load_precheck(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "telbot.planning.transit_ingress_precheck.last_transit_ingress_precheck_path",
        lambda: tmp_path / "precheck.json",
    )
    clear_last_ingress_precheck()
    check = dt.datetime(2026, 6, 1, 17, 50, tzinfo=dt.timezone.utc)
    ingress = dt.datetime(2026, 6, 1, 18, 0, tzinfo=dt.timezone.utc)
    payload = build_precheck_result(
        capture_ok=True,
        reason_code="ok",
        planet="X",
        check_utc=check,
        ingress_utc=ingress,
        expected={},
        max_offset_arcmin=8.0,
        dry_run=True,
    )
    publish_ingress_precheck_result(payload)
    loaded = get_last_ingress_precheck()
    assert loaded is not None
    assert loaded["planet"] == "X"


def test_run_ingress_precheck_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_last_ingress_precheck()
    step = {
        "at_utc": "2026-06-01T17:50:00+00:00",
        "ingress_utc_label": "2026-06-01 18:00 UTC",
        "planet": "WASP-12 b",
        "ra_deg": 97.65,
        "dec_deg": 29.81,
        "exposure_seconds": 5.0,
    }
    s = Settings(latitude=31.2, longitude=121.5)
    monkeypatch.setattr(
        "telbot.planning.transit_ingress_precheck._expected_at_check",
        lambda *_a, **_k: {
            "ra_hours": 6.5,
            "dec_deg": 29.8,
            "altitude_deg": 40.0,
            "azimuth_deg": 180.0,
            "frame": "JNOW",
        },
    )
    out = run_ingress_precheck(s, step, execute=False)
    assert out["dry_run"] is True
    assert out["capture_ok"] is True
    assert get_last_ingress_precheck() is not None


def test_build_transit_plan_includes_ingress_precheck(monkeypatch: pytest.MonkeyPatch) -> None:
    from telbot.planning.transit_plan import build_transit_plan

    s = Settings(
        indi_device="Test Mount",
        indi_ccd_device="Test CCD",
        latitude=31.2,
        longitude=121.5,
        transit_include_ingress_precheck=True,
        transit_exposure_seconds=30.0,
    )
    event = {
        "planet": "WASP-12 b",
        "host": "WASP-12",
        "host_vmag": 11.0,
        "transit_depth_pct": 1.0,
        "transit_duration_h": 2.0,
        "ingress_utc": "2026-06-01 18:00 UTC",
        "egress_utc": "2026-06-01 20:00 UTC",
        "mid_utc": "2026-06-01 19:00 UTC",
        "ra_deg": 97.65,
        "dec_deg": 29.81,
        "fully_observable": True,
    }
    monkeypatch.setattr(
        "telbot.planning.transit_plan.resolve_transit_event",
        lambda *_a, **_k: event,
    )
    night_start = dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.timezone.utc)
    night_end = dt.datetime(2026, 6, 2, 6, 0, tzinfo=dt.timezone.utc)

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
    actions = [st["action"] for st in payload["steps"]]
    assert "ingress_precheck" in actions
    pre = next(st for st in payload["steps"] if st["action"] == "ingress_precheck")
    assert pre["exposure_seconds"] == 30.0
