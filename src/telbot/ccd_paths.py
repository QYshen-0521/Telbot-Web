"""Effective CCD FITS output directory (INDI UPLOAD_DIR should match)."""

from __future__ import annotations

from datetime import date
from pathlib import Path


def capture_date_folder_name(when: date | None = None) -> str:
    """Local calendar day as ``YYYYMMDD`` (e.g. ``20260520``)."""
    return (when or date.today()).strftime("%Y%m%d")


def default_home_ccd_captures_dir() -> Path:
    """
    When TELBOT_CCD_SAVE_DIR is unset: `~/Telbot/data/ccd_captures`.
    FITS for each session go under a ``YYYYMMDD`` subfolder (see ``effective_ccd_save_dir``).
    """
    return (Path.home() / "Telbot" / "data" / "ccd_captures").expanduser().resolve()


def ccd_captures_base_dir(ccd_save_dir_setting: str) -> Path:
    """Root capture directory without the date subfolder."""
    raw = (ccd_save_dir_setting or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return default_home_ccd_captures_dir()


def effective_ccd_save_dir(
    ccd_save_dir_setting: str,
    *,
    when: date | None = None,
) -> Path:
    """
    Directory for today's captures: ``<base>/YYYYMMDD``.

    ``<base>`` is ``TELBOT_CCD_SAVE_DIR`` or ``~/Telbot/data/ccd_captures``.
    Before snap, Telbot sets INDI ``UPLOAD_SETTINGS.UPLOAD_DIR`` to this absolute path.
    """
    return ccd_captures_base_dir(ccd_save_dir_setting) / capture_date_folder_name(when)


def prepare_ccd_save_directory(
    ccd_save_dir_setting: str,
    *,
    when: date | None = None,
    dry_run: bool = False,
    exact_dir: Path | None = None,
) -> Path:
    """Resolve today's save dir and create it when not dry-run.

    If ``exact_dir`` is set, use that path directly (no ``YYYYMMDD`` suffix).
    """
    if exact_dir is not None:
        cap = exact_dir.expanduser().resolve()
        if not dry_run:
            cap.mkdir(parents=True, exist_ok=True)
        return cap
    cap = effective_ccd_save_dir(ccd_save_dir_setting, when=when)
    if not dry_run:
        cap.mkdir(parents=True, exist_ok=True)
    return cap
