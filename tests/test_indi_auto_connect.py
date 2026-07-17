"""INDI auto-connect after USB profile selection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from telbot.indi_auto_connect import (
    collect_connect_jobs,
    parse_indi_drivers_from_args_line,
    resolve_device_for_driver,
)


def _profile_matches(p: dict, vidpids: set[str], by_ids: list[str]) -> bool:
    m = p.get("match") or {}
    vid = (m.get("usb_vid_pid") or "").strip().lower()
    return bool(vid and vid in vidpids)


def _optional_resolved(*_a, **_k):
    return []


@pytest.fixture
def manifest_data():
    path = Path(__file__).resolve().parent.parent / "deploy" / "mount_profiles.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_parse_drivers_from_args_line() -> None:
    assert parse_indi_drivers_from_args_line("-v indi_lx200gemini indi_sbig_ccd") == [
        "indi_lx200gemini",
        "indi_sbig_ccd",
    ]
    assert parse_indi_drivers_from_args_line("-p 7624 -v indi_qhycfw3_wheel") == [
        "indi_qhycfw3_wheel",
    ]


def test_collect_pre_connect_planewave(manifest_data) -> None:
    from telbot.indi_auto_connect import collect_pre_connect_setprops

    jobs = [("indi_planewave_telescope", "PlaneWave")]
    pre = collect_pre_connect_setprops(manifest_data, jobs)
    assert "PlaneWave.DEVICE_ADDRESS.ADDRESS=127.0.0.1" in pre
    assert "PlaneWave.DEVICE_ADDRESS.PORT=8220" in pre


def test_resolve_device_planewave_hint(manifest_data) -> None:
    dev = resolve_device_for_driver(
        "indi_planewave_telescope",
        manifest=manifest_data,
        profile_hint="PlaneWave",
        optional_devices={},
    )
    assert dev == "PlaneWave"


def test_resolve_device_mount_uses_hint(manifest_data) -> None:
    dev = resolve_device_for_driver(
        "indi_lx200gemini",
        manifest=manifest_data,
        profile_hint="Losmandy Gemini",
        optional_devices={},
    )
    assert dev == "Losmandy Gemini"


def test_resolve_device_sbig_explicit(manifest_data) -> None:
    dev = resolve_device_for_driver(
        "indi_sbig_ccd",
        manifest=manifest_data,
        profile_hint="Losmandy Gemini",
        optional_devices={},
    )
    assert dev == "SBIG CCD"


def test_resolve_device_qhy_explicit(manifest_data) -> None:
    dev = resolve_device_for_driver(
        "indi_qhy_ccd",
        manifest=manifest_data,
        profile_hint="Losmandy Gemini",
        optional_devices={},
    )
    assert dev == "QHY CCD QHY174M"


def test_resolve_device_asi_explicit(manifest_data) -> None:
    dev = resolve_device_for_driver(
        "indi_asi_ccd",
        manifest=manifest_data,
        profile_hint="Celestron GPS",
        optional_devices={},
    )
    assert dev == "ZWO CCD ASI294MC Pro"


def test_resolve_simulator_skipped(manifest_data) -> None:
    assert (
        resolve_device_for_driver(
            "indi_simulator_telescope",
            manifest=manifest_data,
            profile_hint="Telescope Simulator",
            optional_devices={},
        )
        is None
    )


def test_collect_jobs_gemini_plus_focuser(manifest_data) -> None:
    prof = next(p for p in manifest_data["profiles"] if p["id"] == "losmandy_gemini_usb")
    args_line = "-v indi_lx200gemini indi_oasis_focuser"
    jobs = collect_connect_jobs(
        manifest_data,
        prof,
        args_line,
        {"1fc9:1705", "338f:a0f0"},
        [],
        profile_matches_fn=_profile_matches,
        optional_drivers_resolved_fn=_optional_resolved,
    )
    names = {dev for _, dev in jobs}
    assert names == {"Losmandy Gemini", "Oasis Focuser"}


def test_collect_jobs_gemini_plus_asi(manifest_data) -> None:
    prof = next(p for p in manifest_data["profiles"] if p["id"] == "losmandy_gemini_usb")
    jobs = collect_connect_jobs(
        manifest_data,
        prof,
        "-v indi_lx200gemini indi_asi_ccd",
        {"1fc9:1705", "03c3:294f"},
        [],
        profile_matches_fn=_profile_matches,
        optional_drivers_resolved_fn=_optional_resolved,
    )
    names = {dev for _, dev in jobs}
    assert names == {"Losmandy Gemini", "ZWO CCD ASI294MC Pro"}


def test_collect_jobs_gemini_plus_qhy(manifest_data) -> None:
    prof = next(p for p in manifest_data["profiles"] if p["id"] == "losmandy_gemini_usb")
    jobs = collect_connect_jobs(
        manifest_data,
        prof,
        "-v indi_lx200gemini indi_qhy_ccd",
        {"1fc9:1705", "1618:c175"},
        [],
        profile_matches_fn=_profile_matches,
        optional_drivers_resolved_fn=_optional_resolved,
    )
    names = {dev for _, dev in jobs}
    assert names == {"Losmandy Gemini", "QHY CCD QHY174M"}


def test_collect_jobs_qhy_only(manifest_data) -> None:
    prof = next(p for p in manifest_data["profiles"] if p["id"] == "qhy174m_usb_only")
    jobs = collect_connect_jobs(
        manifest_data,
        prof,
        "-v indi_qhy_ccd",
        {"1618:c175"},
        [],
        profile_matches_fn=_profile_matches,
        optional_drivers_resolved_fn=_optional_resolved,
    )
    assert jobs == [("indi_qhy_ccd", "QHY CCD QHY174M")]


def test_collect_jobs_zwo_only(manifest_data) -> None:
    prof = next(p for p in manifest_data["profiles"] if p["id"] == "zwo_asi294mc_usb_only")
    jobs = collect_connect_jobs(
        manifest_data,
        prof,
        "-v indi_asi_ccd",
        {"03c3:294f"},
        [],
        profile_matches_fn=_profile_matches,
        optional_drivers_resolved_fn=_optional_resolved,
    )
    assert jobs == [("indi_asi_ccd", "ZWO CCD ASI294MC Pro")]


def test_collect_jobs_focuser_only(manifest_data) -> None:
    prof = next(p for p in manifest_data["profiles"] if p["id"] == "oasis_focuser_usb_only")
    jobs = collect_connect_jobs(
        manifest_data,
        prof,
        "-v indi_oasis_focuser",
        {"338f:a0f0"},
        [],
        profile_matches_fn=_profile_matches,
        optional_drivers_resolved_fn=_optional_resolved,
    )
    assert jobs == [("indi_oasis_focuser", "Oasis Focuser")]
