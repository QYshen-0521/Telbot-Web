from __future__ import annotations

from telbot.config import Settings
from telbot.health_devices import build_health_devices


def _blob_for(*devices: str) -> str:
    lines = []
    for d in devices:
        lines.append(f"{d}.CONNECTION.CONNECT=On")
        lines.append(f"{d}.EQUATORIAL_EOD_COORD.RA=12.0")
    return "\n".join(lines) + "\n"


def test_health_devices_mount_and_ccd_connected() -> None:
    s = Settings(
        indi_device="Losmandy Gemini",
        indi_ccd_device="SBIG CCD",
        indi_focuser_device="",
        indi_cfw_device="",
        indi_device_auto=False,
    )
    blob = _blob_for("Losmandy Gemini", "SBIG CCD")
    out = build_health_devices(s, blob=blob)
    assert out["mount"]["connected"] is True
    assert out["mount"]["name"] == "Losmandy Gemini"
    assert out["camera"]["connected"] is True
    assert out["camera"]["name"] == "SBIG CCD"
    assert "focuser" not in out
    roles = {d["role"] for d in out["devices"]}
    assert roles == {"mount", "ccd"}


def test_health_devices_not_connected_when_connect_off() -> None:
    s = Settings(indi_device="Gemini", indi_ccd_device="SBIG CCD", indi_device_auto=False)
    blob = "Gemini.CONNECTION.CONNECT=Off\nSBIG CCD.CONNECTION.CONNECT=Off\n"
    out = build_health_devices(s, blob=blob)
    assert out["mount"]["present"] is True
    assert out["mount"]["connected"] is False
    assert out["ccd"]["connected"] is False


def test_health_devices_single_getprop(monkeypatch) -> None:
    s = Settings(indi_device="M", indi_ccd_device="C", indi_device_auto=False)
    calls: list[tuple] = []

    def fake_getprop(host, port, pattern, timeout):
        calls.append((pattern, timeout))
        return type("R", (), {"returncode": 0, "stdout": _blob_for("M", "C"), "stderr": ""})()

    monkeypatch.setattr("telbot.health_devices.indi_available", lambda: True)
    monkeypatch.setattr("telbot.health_devices.run_getprop", fake_getprop)
    build_health_devices(s)
    assert len(calls) == 1
    assert calls[0][0] == "*.*.*"


def test_health_endpoint_includes_devices(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from telbot.http_app import app

    monkeypatch.setattr(
        "telbot.http_app.build_health_devices",
        lambda _s, **kw: {
            "mount": {"name": "Losmandy Gemini", "connected": True, "role": "mount"},
            "camera": {"name": "SBIG CCD", "connected": True, "role": "ccd"},
            "devices": [],
        },
    )
    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["mount"]["name"] == "Losmandy Gemini"
    assert data["version"]


def test_health_quick_skips_devices() -> None:
    from fastapi.testclient import TestClient

    from telbot.http_app import app

    c = TestClient(app)
    r = c.get("/health?quick=1")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "mount" not in data
