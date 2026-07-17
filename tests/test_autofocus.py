"""Autofocus HFR metric and dry-run planning."""

from __future__ import annotations

from pathlib import Path

import pytest

from telbot.autofocus.hfr import compute_median_hfr
from telbot.autofocus.run import _sample_positions, run_autofocus
from telbot.config import Settings
from telbot.text_intent import parse_intent_zh


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("astropy"),
    reason="astropy not installed",
)
def test_compute_median_hfr_on_synthetic_gaussian(tmp_path: Path) -> None:
    import numpy as np
    from astropy.io import fits

    size = 64
    y, x = np.ogrid[:size, :size]
    cy, cx = size // 2, size // 2
    sigma = 2.0
    data = np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * sigma**2)).astype(np.float32) * 1000
    # second star
    data += np.exp(-((x - 12) ** 2 + (y - 12) ** 2) / (2 * 2.5**2)).astype(np.float32) * 800
    fits_path = tmp_path / "star.fits"
    fits.writeto(fits_path, data, overwrite=True)
    hfr, stars = compute_median_hfr(fits_path)
    assert hfr is not None
    assert stars >= 1
    assert 1.0 < hfr < 6.0


def test_sample_positions_clamps_to_max() -> None:
    positions = _sample_positions(
        5000,
        half_range=800,
        step=200,
        max_pos=10000,
        margin=50,
    )
    assert all(50 <= p <= 9950 for p in positions)
    assert 5000 in positions


def test_parse_focuser_autofocus_zh() -> None:
    v = parse_intent_zh("帮我自动对焦")
    assert v is not None
    assert v.action == "focuser_autofocus"


def test_parse_focuser_autofocus_not_rel() -> None:
    v = parse_intent_zh("把电调向前移动50")
    assert v is not None
    assert v.action == "focuser_rel"


def test_run_autofocus_dry_run() -> None:
    s = Settings(
        indi_focuser_device="Oasis Focuser",
        indi_ccd_device="QHY CCD QHY174M",
    )
    out = run_autofocus(s, execute=False)
    assert out["ok"] is True
    assert out["dry_run"] is True
    assert out["action"] == "focuser_autofocus"


def test_voice_intent_focuser_autofocus_validates() -> None:
    from telbot.models import VoiceIntentV1

    VoiceIntentV1.model_validate({"version": 1, "action": "focuser_autofocus"})
    VoiceIntentV1.model_validate(
        {"version": 1, "action": "focuser_autofocus", "exposure_seconds": 2.0}
    )
