"""Shared FITS discovery after CCD exposure (snap / calibration / live-stack)."""

from __future__ import annotations

import time
from pathlib import Path

from telbot.platesolve.security import (
    fits_files_in_dir,
    resolve_new_capture_fits,
)


def test_resolve_new_fits_by_path_diff(tmp_path: Path) -> None:
    cap = tmp_path / "bias_session"
    cap.mkdir()
    before = fits_files_in_dir(cap)
    f = cap / "IMAGE_001.fits"
    f.write_bytes(b"bias")
    got = resolve_new_capture_fits(cap, 0, before, retry_attempts=1)
    assert got is not None
    assert got.name == "IMAGE_001.fits"


def test_resolve_in_parent_when_file_not_in_session_dir(tmp_path: Path) -> None:
    day = tmp_path / "20260604"
    session = day / "bias_test"
    session.mkdir(parents=True)
    before_state = {
        session.resolve(): (0, frozenset()),
        day.resolve(): (0, frozenset()),
    }
    f = day / "IMAGE_001.fits"
    f.write_bytes(b"in parent")
    from telbot.platesolve.security import resolve_new_capture_fits_in_dirs

    got = resolve_new_capture_fits_in_dirs(
        [session.resolve(), day.resolve()],
        before_state,
        retry_attempts=1,
    )
    assert got is not None
    assert got.parent == day.resolve()


def test_resolve_indi_overwrites_same_image_path(tmp_path: Path) -> None:
    cap = tmp_path / "session"
    cap.mkdir()
    f = cap / "IMAGE_001.fits"
    f.write_bytes(b"v1")
    before_paths = fits_files_in_dir(cap)
    before_ns = f.stat().st_mtime_ns
    time.sleep(0.05)
    f.write_bytes(b"v2 longer")
    got = resolve_new_capture_fits(cap, before_ns, before_paths, retry_attempts=1)
    assert got is not None
    assert got.name == "IMAGE_001.fits"
