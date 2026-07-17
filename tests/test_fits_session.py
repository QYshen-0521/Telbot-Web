"""FITS session directory and filename hints."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from telbot.fits_session import (
    fits_filename_hint,
    prepare_session_capture_dir,
    session_capture_dir,
    slugify_session_tag,
)


def test_slugify_session_tag() -> None:
    assert slugify_session_tag("transit WASP-12 b") == "transit_WASP-12_b"
    with pytest.raises(ValueError):
        slugify_session_tag("   ")


def test_session_capture_dir(tmp_path: Path) -> None:
    base = tmp_path / "captures"
    p = session_capture_dir(str(base), "WASP12b", when=date(2026, 5, 30))
    assert p == (base / "20260530" / "WASP12b").resolve()


def test_prepare_session_capture_dir_creates(tmp_path: Path) -> None:
    base = tmp_path / "captures"
    cap = prepare_session_capture_dir(str(base), "test_session", when=date(2026, 1, 1), dry_run=False)
    assert cap.is_dir()
    assert cap.name == "test_session"


def test_fits_filename_hint() -> None:
    name = fits_filename_hint(session_tag="WASP12b", frame_index=3, exposure_seconds=2.5, filter_name="Red")
    assert name.startswith("WASP12b_0003_")
    assert "2p5s" in name
    assert "Red" in name
