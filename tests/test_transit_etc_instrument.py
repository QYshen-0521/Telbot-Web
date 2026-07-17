"""ETC instrument auto-resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from telbot.config import Settings
from telbot.planning.transit_etc_instrument import resolve_transit_etc_instrument


def test_resolve_ccd_from_device_name() -> None:
    s = Settings(indi_ccd_device="ZWO CCD ASI294MC Pro")
    r = resolve_transit_etc_instrument(s)
    assert r.pixel_size_um == pytest.approx(3.76)
    assert "catalog.ccd_devices" in r.sources.get("pixel_size_um", "")


def test_resolve_mount_profile_planewave(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "telbot.planning.transit_etc_instrument._read_run_telbot",
        lambda name: "planewave_l350_usb" if name == "mount_profile_id" else "",
    )
    s = Settings()
    r = resolve_transit_etc_instrument(s)
    assert r.aperture_mm == pytest.approx(356)
    assert r.focal_length_mm == pytest.approx(2310)


def test_ota_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELBOT_OTA_APERTURE_MM", "280")
    monkeypatch.setenv("TELBOT_OTA_FOCAL_LENGTH_MM", "1400")
    s = Settings()
    r = resolve_transit_etc_instrument(s)
    assert r.aperture_mm == 280
    assert r.focal_length_mm == 1400
    assert r.sources["aperture_mm"] == "env:TELBOT_OTA_APERTURE_MM"


def test_focal_from_platesolve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    solve_path = tmp_path / "last_solve.json"
    solve_path.write_text(
        json.dumps({"pixel_scale_arcsec_per_pixel": 1.2}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "telbot.repo_paths.platesolve_last_solve_json",
        lambda: solve_path,
    )
    s = Settings(indi_ccd_device="ZWO CCD ASI294MC Pro")
    r = resolve_transit_etc_instrument(s)
    assert r.focal_length_mm == pytest.approx(206.265 * 3.76 / 1.2, rel=0.01)
    assert "platesolve" in r.sources.get("focal_length_mm", "")
