from __future__ import annotations

from pathlib import Path

import pytest

from telbot.config import Settings
from telbot.live_stack.accumulator import LiveStackAccumulator
from telbot.live_stack.runner import run_live_stack
from telbot.live_stack.session import archive_raw_frame, live_stack_session_root


def test_live_stack_dry_run() -> None:
    s = Settings()
    out = run_live_stack(s, duration_seconds=120, exposure_seconds=2, execute=False)
    assert out["ok"] is True
    assert out["dry_run"] is True
    assert out["action"] == "live_stack"
    assert out["duration_seconds"] == 120
    assert out["exposure_seconds"] == 2


def test_live_stack_session_dirs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "telbot.live_stack.session.prepare_session_capture_dir",
        lambda _ccd, tag, **kw: tmp_path / tag,
    )
    root = live_stack_session_root("", "test_sess")
    assert (root / "raw").is_dir()
    assert (root / "stack").is_dir()


def test_accumulator_stack_two_frames(tmp_path) -> None:
    pytest.importorskip("astropy")
    pytest.importorskip("PIL")
    from astropy.io import fits
    import numpy as np

    acc = LiveStackAccumulator()
    for i, dx in enumerate((0, 3)):
        data = np.zeros((32, 32), dtype=np.float32)
        data[10, 10 + dx] = 100.0
        p = tmp_path / f"f{i}.fits"
        fits.PrimaryHDU(data).writeto(p, overwrite=True)
        acc.add_frame(p, align=True)
    assert acc.frame_count == 2
    avg = acc.sum_array / 2
    assert float(avg.max()) > 50


def test_http_live_stack_preview_404() -> None:
    from fastapi.testclient import TestClient

    from telbot.http_app import app

    client = TestClient(app)
    r = client.get("/camera/live-stack/preview")
    assert r.status_code == 404


def test_http_live_stack_start_dry() -> None:
    from fastapi.testclient import TestClient

    from telbot.http_app import app

    client = TestClient(app)
    r = client.post(
        "/camera/live-stack/start?execute=false",
        json={"duration_seconds": 60, "exposure_seconds": 1.0},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data.get("dry_run") is True or data.get("estimated_frames") is not None
