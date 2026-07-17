"""Layperson ``nl_simple`` summaries."""

from telbot.intent_nl import attach_intent_nl
from telbot.intent_nl_simple import build_intent_nl_simple


def test_exoplanet_transits_nl_simple() -> None:
    raw = {
        "ok": True,
        "action": "exoplanet_transits",
        "count": 2,
        "events": [
            {
                "planet": "WASP-12 b",
                "mid_local": "2026-06-03 22:30 CST",
                "difficulty_label": "容易",
                "fully_observable": True,
                "min_altitude_deg": 55.0,
            },
            {
                "planet": "HAT-P-7 b",
                "mid_local": "2026-06-04 01:15 CST",
                "difficulty_label": "中等",
                "fully_observable": False,
                "min_altitude_deg": 28.0,
            },
        ],
    }
    simple = build_intent_nl_simple(raw)
    assert simple is not None
    assert "2 个" in simple["text"]
    assert "WASP-12" in simple["text"]
    assert "22:30" in simple["text"]
    assert "规划第 1 个" in simple["text"]
    assert "凌深" not in simple["text"]
    assert "赤经" not in simple["text"]


def test_plan_exoplanet_transit_nl_simple() -> None:
    raw = {
        "ok": True,
        "action": "plan_exoplanet_transit",
        "event_index": 1,
        "plan": {
            "target": {"planet": "WASP-12 b", "difficulty_label": "容易"},
            "window": {
                "start_utc": "2026-06-03T14:00:00+00:00",
                "end_utc": "2026-06-03T18:00:00+00:00",
                "span_hours": 4.0,
            },
            "instrument_profile": {"exposure_seconds": 120},
        },
    }
    simple = build_intent_nl_simple(raw)
    assert simple is not None
    assert "第 1 个" in simple["text"]
    assert "WASP-12" in simple["text"]
    assert "ETC" not in simple["text"]
    assert "SNR" not in simple["text"]


def test_attach_includes_nl_simple_for_transits() -> None:
    raw = {
        "ok": True,
        "action": "exoplanet_transits",
        "events": [{"planet": "X b", "mid_local": "2026-06-03 20:00 UTC", "difficulty_label": "容易"}],
    }
    merged = attach_intent_nl(raw)
    assert "nl" in merged
    assert "nl_simple" in merged
    assert "X b" in merged["nl_simple"]["text"]


def test_goto_has_no_nl_simple() -> None:
    raw = {"ok": True, "action": "goto", "dry_run": True, "resolved": {"label": "木星"}}
    assert build_intent_nl_simple(raw) is None
    merged = attach_intent_nl(raw)
    assert "nl_simple" not in merged
