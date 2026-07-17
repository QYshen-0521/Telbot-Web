"""Snap preview FITS resolution (App 拍单张)."""

from __future__ import annotations

from pathlib import Path

from telbot.platesolve.security import fits_files_in_dir, resolve_new_capture_fits

resolve_new_snap_fits = resolve_new_capture_fits


def test_resolve_new_snap_fits_by_path_diff(tmp_path: Path) -> None:
    cap = tmp_path / "20260604"
    cap.mkdir()
    old = cap / "IMAGE_001.fits"
    old.write_bytes(b"old")
    before = fits_files_in_dir(cap)
    new = cap / "IMAGE_002.fits"
    new.write_bytes(b"new")
    got = resolve_new_snap_fits(cap, old.stat().st_mtime_ns, before)
    assert got is not None
    assert got.name == "IMAGE_002.fits"


def test_resolve_new_snap_fits_recent_fallback(tmp_path: Path) -> None:
    cap = tmp_path / "day"
    cap.mkdir()
    f = cap / "IMAGE_001.fits"
    f.write_bytes(b"x")
    before = frozenset()
    got = resolve_new_snap_fits(cap, 0, before, snap_grace_seconds=300.0)
    assert got == f.resolve()
