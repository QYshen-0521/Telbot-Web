"""Transit exposure time calculator (ETC)."""

from __future__ import annotations

import pytest

from telbot.config import Settings
from telbot.planning.transit_etc import compute_transit_exposure


def _event(**kw: object) -> dict:
    base = {
        "planet": "WASP-12 b",
        "host_vmag": 11.7,
        "transit_depth_pct": 1.5,
    }
    base.update(kw)
    return base


def test_etc_returns_exposure_in_json_shape() -> None:
    s = Settings()
    out = compute_transit_exposure(s, _event())
    assert out["schema_version"] == "telbot.transit_etc.v1"
    assert out["exposure_seconds"] >= s.transit_etc_min_exposure_seconds
    assert out["cadence_seconds"] == out["exposure_seconds"] + s.expose_loop_overhead_seconds
    assert out["method"] == "photon_noise_depth_snr_v1"
    assert "inputs" in out and "computed" in out
    assert out["computed"]["photometry_snr_at_exposure"] > 0


def test_deeper_transit_needs_shorter_or_similar_exposure() -> None:
    s = Settings(transit_etc_max_exposure_seconds=600.0)
    shallow = compute_transit_exposure(s, _event(transit_depth_pct=0.5))
    deep = compute_transit_exposure(s, _event(transit_depth_pct=3.0))
    assert deep["exposure_seconds"] <= shallow["exposure_seconds"]


def test_saturation_caps_long_exposure() -> None:
    s = Settings(
        transit_etc_full_well_e=5000.0,
        transit_etc_aperture_mm=400.0,
    )
    out = compute_transit_exposure(s, _event(host_vmag=8.0))
    assert out["exposure_seconds"] <= s.transit_etc_max_exposure_seconds


def test_build_plan_includes_etc_block(monkeypatch: pytest.MonkeyPatch) -> None:
    from telbot.planning.transit_plan import build_transit_plan, parse_event_utc_label

    event = {
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
    s = Settings(
        indi_device="M",
        indi_ccd_device="C",
        transit_exposure_seconds=0.0,
    )
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
    assert "etc" in inst
    assert inst["etc"]["method"] == "photon_noise_depth_snr_v1"
    assert inst["exposure_seconds"] == inst["etc"]["exposure_seconds"]
    loop = next(st for st in payload["steps"] if st["action"] == "expose_loop")
    assert loop["exposure_seconds"] == inst["exposure_seconds"]


def test_manual_cli_override_skips_etc() -> None:
    from telbot.planning.transit_plan import _resolve_exposure_and_cadence

    s = Settings()
    exp, cad, etc, warns = _resolve_exposure_and_cadence(
        s, _event(), exposure_override=42.0
    )
    assert exp == 42.0
    assert etc["method"] == "manual_cli_override"
    assert any("手动" in w for w in warns)
