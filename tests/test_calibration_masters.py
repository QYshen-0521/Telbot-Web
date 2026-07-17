from __future__ import annotations

from pathlib import Path

import pytest

from telbot.calibration_masters import CalibrationMasters


def test_calibration_apply_bias_dark_flat() -> None:
    pytest.importorskip("astropy")
    import numpy as np

    light = np.ones((8, 8), dtype=np.float32) * 100.0
    bias = np.ones((8, 8), dtype=np.float64) * 10.0
    dark = np.ones((8, 8), dtype=np.float64) * 5.0
    flat_norm = np.ones((8, 8), dtype=np.float64) * 2.0

    masters = CalibrationMasters(bias=bias, dark=dark, flat=flat_norm)
    masters._flat_norm = flat_norm
    out = masters.apply(light)
    # (100 - 10 - 5) / 2 = 42.5
    assert abs(float(out[0, 0]) - 42.5) < 0.01


def test_median_master_from_dir(tmp_path) -> None:
    pytest.importorskip("astropy")
    from astropy.io import fits
    import numpy as np

    from telbot.calibration_masters import median_master_from_dir

    for i in range(3):
        data = np.full((4, 4), float(10 + i), dtype=np.float32)
        fits.PrimaryHDU(data).writeto(tmp_path / f"b{i}.fits", overwrite=True)
    master = median_master_from_dir(tmp_path)
    assert float(master[0, 0]) == 11.0


def test_list_calibration_fits_prefers_archived_names(tmp_path: Path) -> None:
    from telbot.calibration_masters import list_calibration_fits

    (tmp_path / "IMAGE_001.fits").write_bytes(b"")
    (tmp_path / "bias_0001.fits").write_bytes(b"")
    (tmp_path / "bias_0002.fits").write_bytes(b"")
    paths = list_calibration_fits(tmp_path, kind="bias")
    names = [p.name for p in paths]
    assert names == ["bias_0001.fits", "bias_0002.fits"]


def test_live_stack_dry_run_with_cal_paths() -> None:
    from telbot.config import Settings
    from telbot.live_stack.runner import run_live_stack

    s = Settings()
    out = run_live_stack(
        s,
        duration_seconds=60,
        exposure_seconds=1,
        cal_bias_dir="/tmp/cal_bias_test",
        cal_dark_dir="/tmp/cal_dark_test",
        execute=False,
    )
    assert out["calibration"]["enabled"] is True
    assert out["calibration"]["bias_dir"] == "/tmp/cal_bias_test"
