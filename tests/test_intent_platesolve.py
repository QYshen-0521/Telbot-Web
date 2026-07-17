"""VoiceIntent platesolve (snap + solve path)."""

from __future__ import annotations

import pytest

from telbot.config import Settings
from telbot.indi import IndiResult
from telbot.intent_exec import execute_voice_intent
from telbot.models import VoiceIntentV1


def test_execute_platesolve_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("telbot.intent_exec.ccd_is_connected", lambda *a, **k: True)
    monkeypatch.setattr(
        "telbot.intent_exec.ccd_prepare_for_capture",
        lambda *a, **k: [IndiResult(0, "[dry-run]", "")],
    )
    monkeypatch.setattr(
        "telbot.intent_exec.ccd_snap_exposure",
        lambda *a, **kw: ([IndiResult(0, "[dry-run]", "")], {"waited": False}),
    )
    s = Settings()
    out = execute_voice_intent(s, VoiceIntentV1(version=1, action="platesolve"), execute=False)
    assert out["action"] == "platesolve"
    assert out["dry_run"] is True
    assert out["snap"]["ok"] is True
    assert out["solve"]["skipped"] == "dry_run"


def test_execute_platesolve_real_snap_then_solve(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cap = tmp_path / "ccd"
    cap.mkdir()
    monkeypatch.setattr("telbot.intent_exec.prepare_ccd_save_directory", lambda *a, **k: cap.resolve())
    monkeypatch.setattr(
        "telbot.intent_exec.ccd_prepare_for_capture",
        lambda *a, **k: [IndiResult(0, "", "")],
    )
    monkeypatch.setattr("telbot.intent_exec.ccd_is_connected", lambda *a, **k: True)

    def fake_snap(
        device: str,
        host: str,
        port: int,
        exposure_seconds: float,
        *,
        dry_run: bool,
        **kwargs,
    ):
        if not dry_run:
            (cap / "new.fits").write_bytes(b"x")
        return ([IndiResult(0, "", "")], {"waited": True})

    monkeypatch.setattr("telbot.intent_exec.ccd_snap_exposure", fake_snap)

    def fake_run(_s, *, fits_path, use_latest):
        assert fits_path is not None
        assert fits_path.name == "new.fits"
        assert use_latest is False
        return {"ok": True, "message": "ok", "backend": "astap"}

    monkeypatch.setattr("telbot.platesolve.service.run_platesolve", fake_run)

    s = Settings()
    out = execute_voice_intent(s, VoiceIntentV1(version=1, action="platesolve"), execute=True)
    assert out["ok"] is True
    assert out["action"] == "platesolve"
    assert "snap" in out
    assert out.get("backend") == "astap"


def test_execute_platesolve_with_sync_align(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cap = tmp_path / "ccd"
    cap.mkdir()
    monkeypatch.setattr("telbot.intent_exec.prepare_ccd_save_directory", lambda *a, **k: cap.resolve())
    monkeypatch.setattr(
        "telbot.intent_exec.ccd_prepare_for_capture",
        lambda *a, **k: [IndiResult(0, "", "")],
    )
    monkeypatch.setattr("telbot.intent_exec.ccd_is_connected", lambda *a, **k: True)

    def fake_snap(
        device: str,
        host: str,
        port: int,
        exposure_seconds: float,
        *,
        dry_run: bool,
        **kwargs,
    ):
        if not dry_run:
            (cap / "new.fits").write_bytes(b"x")
        return ([IndiResult(0, "", "")], {"waited": True})

    monkeypatch.setattr("telbot.intent_exec.ccd_snap_exposure", fake_snap)

    def fake_run(_s, *, fits_path, use_latest):
        return {
            "ok": True,
            "message": "ok",
            "backend": "astap",
            "jnow_ra_hours": 1.0,
            "jnow_dec_deg": 2.0,
        }

    monkeypatch.setattr("telbot.platesolve.service.run_platesolve", fake_run)

    calls: list[tuple[str, bool]] = []

    def fake_align(s, solve_out, *, align, execute, on_before_real=None):
        calls.append((align, execute))
        return {"ok": True, "mode": align}

    monkeypatch.setattr("telbot.platesolve_align.align_mount_after_platesolve", fake_align)

    s = Settings()
    out = execute_voice_intent(
        s,
        VoiceIntentV1(version=1, action="platesolve", platesolve_align="sync"),
        execute=True,
    )
    assert out["ok"] is True
    assert calls == [("sync", True)]
    assert out["align"]["mode"] == "sync"
