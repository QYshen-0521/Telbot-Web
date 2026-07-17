"""Plate solve path checks and HTTP wiring (no real ASTAP)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from telbot.config import load_settings
from telbot.http_app import app
from telbot.platesolve.security import resolve_and_check_fits_path

client = TestClient(app)


def test_resolve_accepts_file_under_allowed_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "cap"
    root.mkdir()
    fits = root / "test.fits"
    fits.write_bytes(b"")
    s = load_settings()
    monkeypatch.setattr(
        "telbot.platesolve.security.allowed_fits_roots",
        lambda _settings: [root.resolve()],
    )
    p = resolve_and_check_fits_path(str(fits), s)
    assert p == fits.resolve()


def test_resolve_rejects_file_outside_allowed_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.fits"
    outside.write_bytes(b"")
    s = load_settings()
    monkeypatch.setattr(
        "telbot.platesolve.security.allowed_fits_roots",
        lambda _settings: [allowed.resolve()],
    )
    with pytest.raises(ValueError, match="允许"):
        resolve_and_check_fits_path(str(outside), s)


def test_post_platesolve_use_latest_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "telbot.http_app.run_platesolve",
        lambda _s, **kw: {"ok": True, "message": "ok"},
    )
    r = client.post("/platesolve", json={"use_latest": True})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "align" not in r.json()


def test_post_platesolve_align_execute_calls_align(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("telbot.http_app.indi_available", lambda: True)
    monkeypatch.setattr(
        "telbot.http_app.run_platesolve",
        lambda _s, **kw: {
            "ok": True,
            "message": "ok",
            "jnow_ra_hours": 1.0,
            "jnow_dec_deg": 2.0,
        },
    )

    def fake_align(s, out, *, align, execute, on_before_real=None):
        return {"ok": True, "mode": align, "execute": execute, "steps": [{"stage": "test"}]}

    monkeypatch.setattr("telbot.http_app.align_mount_after_platesolve", fake_align)
    r = client.post(
        "/platesolve",
        json={"use_latest": True, "execute": True, "align": "sync"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["align"]["ok"] is True
    assert body["align"]["mode"] == "sync"


def test_post_platesolve_align_skipped_when_solve_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "telbot.http_app.run_platesolve",
        lambda _s, **kw: {"ok": False, "message": "ASTAP 失败"},
    )
    r = client.post(
        "/platesolve",
        json={"use_latest": True, "execute": True, "align": "sync"},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["ok"] is False
    assert b["align"]["skipped"] == "solve_not_ok"
    assert b["align"]["ok"] is False


def test_post_platesolve_align_without_execute_422() -> None:
    r = client.post("/platesolve", json={"use_latest": True, "align": "sync", "execute": False})
    assert r.status_code == 422


def test_post_platesolve_snap_first_422_without_execute() -> None:
    r = client.post("/platesolve", json={"snap_first": True, "execute": False})
    assert r.status_code == 422


def test_post_platesolve_snap_first_flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cap = tmp_path / "Telbot" / "data" / "ccd_captures"
    cap.mkdir(parents=True)
    monkeypatch.setattr("telbot.http_app.indi_available", lambda: True)
    monkeypatch.setattr("telbot.http_app.effective_ccd_save_dir", lambda _s: cap.resolve())

    def fake_snap(s, intent, *, execute, on_before_real=None):
        (cap / "capture.fits").write_bytes(b"x")
        return {"ok": True, "action": "snap", "dry_run": False}

    monkeypatch.setattr("telbot.http_app.execute_voice_intent", fake_snap)
    monkeypatch.setattr(
        "telbot.http_app.run_platesolve",
        lambda s, **kw: {"ok": True, "input_used": str(kw.get("fits_path"))},
    )
    r = client.post("/platesolve", json={"snap_first": True, "execute": True})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert "snap" in j
    assert "capture.fits" in j["input_used"]


def test_newest_fits_after_mtime_ns(tmp_path: Path) -> None:
    from telbot.platesolve.security import max_fits_mtime_ns_in_dir, newest_fits_after_mtime_ns

    d = tmp_path / "ccd"
    d.mkdir()
    (d / "old.fits").write_bytes(b"1")
    before = max_fits_mtime_ns_in_dir(d)
    (d / "new.fits").write_bytes(b"2")
    n = newest_fits_after_mtime_ns(d, before)
    assert n is not None
    assert n.name == "new.fits"


def test_post_platesolve_conflicting_body_422() -> None:
    r = client.post("/platesolve", json={"use_latest": True, "fits_path": "/x.fits"})
    assert r.status_code == 422


def test_post_platesolve_invalid_path_400() -> None:
    r = client.post("/platesolve", json={"fits_path": "/no/such/file.fits"})
    assert r.status_code == 400
