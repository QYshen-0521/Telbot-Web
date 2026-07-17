"""Preflight device readiness diagnostics."""

from __future__ import annotations

from telbot.config import Settings
from telbot.preflight import _device_in_getprop, _parse_on_off, run_preflight
from telbot.text_intent import parse_intent_zh


def test_device_in_getprop() -> None:
    blob = "PlaneWave.CONNECTION.CONNECT=On\nQHY CCD.CONNECTION.CONNECT=Off\n"
    assert _device_in_getprop(blob, "PlaneWave")
    assert not _device_in_getprop(blob, "Missing")


def test_parse_on_off() -> None:
    blob = "PlaneWave.TELESCOPE_PARK.PARK=Off\nPlaneWave.TELESCOPE_PARK.UNPARK=On\n"
    assert _parse_on_off(blob, "PlaneWave", "TELESCOPE_PARK", "UNPARK") == "On"


def test_run_preflight_offline_minimal(monkeypatch) -> None:
    monkeypatch.setattr("telbot.preflight.indi_available", lambda: False)
    s = Settings(latitude=31.2, longitude=121.5)
    out = run_preflight(s, include_indi_service=False)
    assert out["action"] == "preflight"
    assert out["ready"] is False
    ids = {c["id"] for c in out["checks"]}
    assert "indi_tools" in ids
    assert "observer" in ids
    assert "ccd_save_dir" in ids


def test_run_preflight_observer_warn() -> None:
    from telbot.preflight import run_preflight as rp

    out = rp(Settings(), include_indi_service=False)
    obs = next(c for c in out["checks"] if c["id"] == "observer")
    assert obs["status"] == "warn"


def test_parse_preflight_intent() -> None:
    v = parse_intent_zh("检查一下设备是否就绪")
    assert v is not None
    assert v.action == "preflight"


def test_voice_intent_preflight_validates() -> None:
    from telbot.models import VoiceIntentV1

    VoiceIntentV1.model_validate({"version": 1, "action": "preflight"})
