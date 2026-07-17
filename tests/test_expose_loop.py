"""expose_loop dry-run and mocked execute."""

from __future__ import annotations

import datetime as dt

import pytest

from telbot.config import Settings
from telbot.expose_loop import run_expose_loop
from telbot.scheduling.abort import AbortController


def test_expose_loop_dry_run_duration() -> None:
    s = Settings(expose_loop_overhead_seconds=5.0, ccd_default_exposure_seconds=2.0)
    out = run_expose_loop(s, duration_seconds=60.0, execute=False)
    assert out["ok"]
    assert out["dry_run"]
    assert out["exposure_seconds"] == 2.0
    assert out["cadence_seconds"] == 7.0
    assert out["estimated_frames"] >= 8


def test_expose_loop_dry_run_until() -> None:
    s = Settings()
    until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)
    out = run_expose_loop(s, until_utc=until, exposure_seconds=1.0, cadence_seconds=2.0, execute=False)
    assert out["ok"]
    assert out["dry_run"]
    assert out["estimated_frames"] >= 290


def test_expose_loop_requires_one_of_until_or_duration() -> None:
    s = Settings()
    with pytest.raises(ValueError, match="until_utc"):
        run_expose_loop(s, execute=False)
    with pytest.raises(ValueError, match="until_utc"):
        run_expose_loop(s, until_utc=dt.datetime.now(dt.timezone.utc), duration_seconds=10.0, execute=False)


def test_expose_loop_mock_execute() -> None:
    s = Settings()
    calls: list[float] = []
    abort = AbortController()

    def fake_snap(_settings: object, exposure: float, _cap_dir: object) -> dict:
        calls.append(exposure)
        abort.request("done")
        return {"ok": True}

    out = run_expose_loop(
        s,
        duration_seconds=60.0,
        exposure_seconds=1.0,
        cadence_seconds=2.0,
        execute=True,
        snap_fn=fake_snap,
        abort=abort,
    )
    assert out["ok"]
    assert out.get("aborted")
    assert out["frames_completed"] == 1
    assert calls == [1.0]
