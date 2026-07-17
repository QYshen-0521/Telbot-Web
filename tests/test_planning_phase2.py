"""Planning phase 2: azimuth parsing, schedule blocks (no OpenNGC required)."""

from __future__ import annotations

import datetime as dt

from telbot.planning.phase2_schedule import (
    azimuth_in_forbidden,
    parse_forbidden_azimuth_ranges,
    schedule_exposure_blocks,
)


def test_parse_forbidden_azimuth_ranges() -> None:
    r = parse_forbidden_azimuth_ranges("10-80 , 200-300")
    assert len(r) == 2
    assert r[0] == (10.0, 80.0)


def test_azimuth_in_forbidden_wrap() -> None:
    r = parse_forbidden_azimuth_ranges("350-10")
    assert azimuth_in_forbidden(5.0, r)
    assert not azimuth_in_forbidden(90.0, r)


def test_schedule_advanced_no_meridian_skip() -> None:
    w0 = dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.timezone.utc)
    w1 = dt.datetime(2026, 6, 15, 20, 0, tzinfo=dt.timezone.utc)
    peak = dt.datetime(2026, 6, 15, 14, 0, tzinfo=dt.timezone.utc)
    ordered = [
        {
            "catalog_id": "M1",
            "meridian_peak_utc": peak,
        }
    ]
    blocks, unsched = schedule_exposure_blocks(
        ordered,
        window_start=w0,
        window_end=w1,
        goto_buffer_s=60.0,
        exposure_s=60.0,
        meridian_buffer_minutes=60.0,
        strategy="advanced",
    )
    assert len(blocks) == 1
    assert not unsched


def test_schedule_conservative_skips_overlap() -> None:
    # 窗口完全落在子午线禁区 [peak±buffer] 与窗口交集内，无法插入 2min 块
    w0 = dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.timezone.utc)
    w1 = dt.datetime(2026, 6, 15, 12, 45, tzinfo=dt.timezone.utc)
    peak = dt.datetime(2026, 6, 15, 12, 30, tzinfo=dt.timezone.utc)
    ordered = [
        {
            "catalog_id": "M1",
            "meridian_peak_utc": peak,
        }
    ]
    blocks, unsched = schedule_exposure_blocks(
        ordered,
        window_start=w0,
        window_end=w1,
        goto_buffer_s=60.0,
        exposure_s=60.0,
        meridian_buffer_minutes=30.0,
        strategy="conservative",
    )
    assert not blocks
    assert unsched == ["M1"]
