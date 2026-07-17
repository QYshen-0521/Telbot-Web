"""Exoplanet transit listing (difficulty, intent, optional astroplan integration)."""

from __future__ import annotations

import datetime as dt

import pytest

from telbot.config import Settings
from telbot.exoplanet_transits import (
    PlanetEphemeris,
    _float_or_none,
    _row_to_planet,
    build_exoplanet_transit_report,
    compute_difficulty_score,
    difficulty_label,
    format_transit_events_message,
    scan_observable_transits,
)
from telbot.intent_nl import build_intent_nl
from telbot.models import VoiceIntentV1
from telbot.text_intent import parse_intent_zh


def test_difficulty_score_brighter_is_easier() -> None:
    easy = compute_difficulty_score(
        host_vmag=9.0,
        transit_depth_pct=2.0,
        min_altitude_deg=50.0,
        moon_separation_deg=80.0,
        fully_observable=True,
    )
    hard = compute_difficulty_score(
        host_vmag=11.5,
        transit_depth_pct=0.3,
        min_altitude_deg=32.0,
        moon_separation_deg=20.0,
        fully_observable=False,
    )
    assert easy < hard
    assert difficulty_label(easy) in ("容易", "中等")
    assert difficulty_label(hard) in ("中等", "困难")


def test_row_to_planet_accepts_pscomppars_ra_dec() -> None:
    from types import SimpleNamespace

    row = SimpleNamespace(
        pl_name="WASP-12 b",
        hostname="WASP-12",
        ra=97.65,
        dec=29.45,
        sy_vmag=11.6,
        pl_tranmid=2456305.0,
        pl_orbper=1.091,
        pl_trandur=2.5,
        pl_trandep=1.55,
    )
    p = _row_to_planet(row)
    assert p is not None
    assert p.pl_name == "WASP-12 b"
    assert p.ra_deg == 97.65
    assert p.dec_deg == 29.45


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("astropy"),
    reason="astropy not installed",
)
def test_row_to_planet_accepts_astropy_quantity_cells() -> None:
    import astropy.units as u
    from astropy.table import Row, Table

    table = Table(
        {
            "pl_name": ["HD 219134 c"],
            "hostname": ["HD 219134"],
            "ra": [348.3372026 * u.deg],
            "dec": [57.1696255 * u.deg],
            "sy_vmag": [5.56911],
            "pl_tranmid": [2457474.04591 * u.d],
            "pl_orbper": [6.76458 * u.d],
            "pl_trandur": [1.66 * u.hour],
            "pl_trandep": [0.0318 * u.percent],
        }
    )
    row: Row = table[0]
    p = _row_to_planet(row)
    assert p is not None
    assert p.pl_name == "HD 219134 c"
    assert p.ra_deg == pytest.approx(348.3372026)
    assert p.dec_deg == pytest.approx(57.1696255)
    assert p.host_vmag == pytest.approx(5.56911)
    assert p.tran_mid_jd == pytest.approx(2457474.04591)
    assert p.orb_period_days == pytest.approx(6.76458)
    assert p.tran_dur_hours == pytest.approx(1.66)
    assert p.tran_depth_pct == pytest.approx(0.0318)


def test_float_or_none_numpy_scalar() -> None:
    import numpy as np

    assert _float_or_none(np.float64(5.56911)) == pytest.approx(5.56911)


def test_format_transit_events_message_empty() -> None:
    msg = format_transit_events_message([], window_label="今晚：")
    assert "没有" in msg


def test_text_intent_exoplanet_transits() -> None:
    intent = parse_intent_zh("今晚可观测的系外行星事件有哪些？")
    assert intent is not None
    assert intent.action == "exoplanet_transits"


def test_text_intent_plan_exoplanet_transit() -> None:
    intent = parse_intent_zh("帮我规划第2个凌星观测")
    assert intent is not None
    assert intent.action == "plan_exoplanet_transit"
    assert intent.event_index == 2
    intent2 = parse_intent_zh("今晚观测 WASP-12 b 凌星")
    assert intent2 is not None
    assert intent2.action == "plan_exoplanet_transit"
    assert "WASP-12" in (intent2.target or "")


def test_intent_nl_exoplanet_lines() -> None:
    raw = {
        "ok": True,
        "action": "exoplanet_transits",
        "message": "观测窗：共 1 个可观测凌星事件（按难度从低到高）：\n1. WASP-12 b — 容易",
        "events": [{"planet": "WASP-12 b", "difficulty_label": "容易"}],
        "count": 1,
    }
    nl = build_intent_nl(raw)
    assert "WASP-12" in nl["text"]


def _fake_wasp12() -> list[PlanetEphemeris]:
    return [
        PlanetEphemeris(
            pl_name="WASP-12 b",
            hostname="WASP-12",
            ra_deg=97.65,
            dec_deg=29.45,
            host_vmag=11.6,
            tran_mid_jd=2456305.0,
            orb_period_days=1.091,
            tran_dur_hours=2.5,
            tran_depth_pct=1.55,
        )
    ]


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("astroplan"),
    reason="astroplan not installed",
)
def test_scan_observable_transits_with_fake_catalog() -> None:
    s = Settings(
        latitude=31.2,
        longitude=121.5,
        elevation_m=10.0,
        exoplanet_min_altitude_deg=25.0,
        exoplanet_max_results=5,
        exoplanet_consider_moon=False,
    )
    # Wide window around a known epoch; may yield 0 events if geometry does not match.
    start = dt.datetime(2018, 9, 1, 0, 0, tzinfo=dt.timezone.utc)
    end = dt.datetime(2018, 9, 3, 0, 0, tzinfo=dt.timezone.utc)
    events = scan_observable_transits(
        s,
        _fake_wasp12(),
        window_start_utc=start,
        window_end_utc=end,
        min_altitude_deg=25.0,
        max_results=5,
        consider_moon=False,
    )
    for ev in events:
        assert "difficulty_score" in ev
        assert "planet" in ev
        assert "mid_local" in ev
    if events:
        assert events == sorted(events, key=lambda e: e["difficulty_score"])


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("astroplan"),
    reason="astroplan not installed",
)
def test_build_report_with_mock_fetch() -> None:
    s = Settings(latitude=31.2, longitude=121.5, elevation_m=10.0)
    out = build_exoplanet_transit_report(
        s,
        fetch_fn=lambda **_: _fake_wasp12(),
        from_iso="2018-09-01T00:00:00+00:00",
        to_iso="2018-09-03T00:00:00+00:00",
    )
    assert out["action"] == "exoplanet_transits"
    assert out["ok"] is True
    assert "events" in out
    assert VoiceIntentV1.model_validate({"version": 1, "action": "exoplanet_transits"})
