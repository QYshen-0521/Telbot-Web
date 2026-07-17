from __future__ import annotations

import warnings

from telbot.ccd_resolve import resolve_ccd_device_from_getprop_stdout
from telbot.config import Settings
from telbot.health_devices import build_health_devices


def _sbig_blob(connected: bool = True) -> str:
    on = "On" if connected else "Off"
    return (
        f"Losmandy Gemini.CONNECTION.CONNECT=On\n"
        f"SBIG CCD.CONNECTION.CONNECT={on}\n"
        f"SBIG CCD.CCD_EXPOSURE.CCD_EXPOSURE_VALUE=1.0\n"
        f"SBIG CCD.CCD_INFO.CCD_INFO_WIDTH=1024\n"
    )


def test_resolve_ccd_prefers_detected_sbig_over_default_zwo() -> None:
    s = Settings(indi_ccd_device="", indi_device_auto=False)
    name = resolve_ccd_device_from_getprop_stdout(s, _sbig_blob())
    assert name == "SBIG CCD"


def test_resolve_ccd_keeps_configured_when_in_blob() -> None:
    s = Settings(indi_ccd_device="SBIG CCD", indi_device_auto=False)
    assert resolve_ccd_device_from_getprop_stdout(s, _sbig_blob()) == "SBIG CCD"


def test_health_devices_sbig_connected_when_env_still_zwo_default() -> None:
    s = Settings(
        indi_device="Losmandy Gemini",
        indi_ccd_device="",
        indi_device_auto=False,
    )
    out = build_health_devices(s, blob=_sbig_blob(connected=True))
    assert out["camera"]["name"] == "SBIG CCD"
    assert out["camera"]["connected"] is True
    assert out["camera"]["present"] is True


def test_resolve_warns_when_configured_name_missing() -> None:
    s = Settings(indi_ccd_device="ZWO CCD ASI294MC Pro", indi_device_auto=False)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        name = resolve_ccd_device_from_getprop_stdout(s, _sbig_blob())
    assert name == "SBIG CCD"
    assert any("TELBOT_INDI_CCD_DEVICE" in str(x.message) for x in w)
