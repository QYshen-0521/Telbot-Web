"""Mount align after plate solve (mocked INDI / horizon)."""

from __future__ import annotations

import pytest

from telbot.config import Settings
from telbot.indi import IndiResult
from telbot.platesolve_align import align_mount_after_platesolve


def test_align_missing_jnow_returns_error() -> None:
    s = Settings()
    out = {"ok": True, "message": "ok"}
    r = align_mount_after_platesolve(s, out, align="sync", execute=False)
    assert r["ok"] is False
    assert "JNow" in (r.get("error") or "")


def test_align_sync_calls_indi(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, float, float, bool]] = []

    def fake_sync(
        device: str,
        host: str,
        port: int,
        ra_hours: float,
        dec_deg: float,
        *,
        dry_run: bool,
        on_before_real=None,
    ):
        calls.append((device, ra_hours, dec_deg, dry_run))
        return IndiResult(0, "c1", ""), IndiResult(0, "c2", "")

    monkeypatch.setattr("telbot.platesolve_align.sync_equatorial_eod", fake_sync)
    monkeypatch.setattr("telbot.platesolve_align.resolve_telescope_device", lambda _s: "MountX")
    monkeypatch.setattr("telbot.platesolve_align.ensure_above_horizon", lambda *a, **k: 40.0)

    s = Settings()
    out = {"ok": True, "jnow_ra_hours": 2.5, "jnow_dec_deg": 8.0}
    r = align_mount_after_platesolve(s, out, align="sync", execute=True)
    assert r["ok"] is True
    assert calls == [("MountX", 2.5, 8.0, False)]


def test_align_slew_uses_slew(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_slew(device, host, port, ra_hours, dec_deg, *, dry_run, on_before_real=None):
        calls.append("slew")
        return IndiResult(0, "", ""), IndiResult(0, "", "")

    monkeypatch.setattr("telbot.platesolve_align.slew_equatorial_eod", fake_slew)
    monkeypatch.setattr("telbot.platesolve_align.resolve_telescope_device", lambda _s: "M")
    monkeypatch.setattr("telbot.platesolve_align.ensure_above_horizon", lambda *a, **k: 1.0)

    s = Settings()
    out = {"ok": True, "jnow_ra_hours": 0.1, "jnow_dec_deg": 5.0}
    r = align_mount_after_platesolve(s, out, align="slew", execute=False)
    assert r["ok"] is True
    assert r["dry_run"] is True
    assert calls == ["slew"]
