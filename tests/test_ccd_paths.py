"""CCD save directory resolution."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from telbot.ccd_paths import (
    capture_date_folder_name,
    ccd_captures_base_dir,
    default_home_ccd_captures_dir,
    effective_ccd_save_dir,
    prepare_ccd_save_directory,
)


def test_effective_ccd_save_dir_default_with_date_subfolder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    d = date(2026, 5, 20)
    p = effective_ccd_save_dir("", when=d)
    assert p == (tmp_path / "Telbot" / "data" / "ccd_captures" / "20260520").resolve()


def test_effective_ccd_save_dir_explicit_with_date(tmp_path: Path) -> None:
    custom = tmp_path / "myfits"
    custom.mkdir()
    p = effective_ccd_save_dir(str(custom), when=date(2026, 1, 2))
    assert p == (custom / "20260102").resolve()


def test_prepare_ccd_save_directory_creates_folder(tmp_path: Path) -> None:
    base = tmp_path / "ccd_captures"
    cap = prepare_ccd_save_directory(str(base), when=date(2026, 5, 20), dry_run=False)
    assert cap.is_dir()
    assert cap.name == "20260520"


def test_capture_date_folder_name() -> None:
    assert capture_date_folder_name(date(2026, 5, 20)) == "20260520"


def test_default_home_ccd_captures_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_home_ccd_captures_dir() == (tmp_path / "Telbot" / "data" / "ccd_captures").resolve()


def test_ccd_captures_base_dir() -> None:
    assert ccd_captures_base_dir("") == default_home_ccd_captures_dir()
