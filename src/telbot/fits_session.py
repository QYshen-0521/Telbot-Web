"""FITS capture session directories and naming hints."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from telbot.ccd_paths import ccd_captures_base_dir, capture_date_folder_name


def slugify_session_tag(tag: str) -> str:
    """Safe directory segment from user/session name."""
    s = tag.strip()
    if not s:
        raise ValueError("session_tag 不能为空")
    s = re.sub(r"[^\w\-+.]+", "_", s, flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        raise ValueError("session_tag 无有效字符")
    return s[:80]


def session_capture_dir(
    ccd_save_dir_setting: str,
    session_tag: str,
    *,
    when: date | None = None,
) -> Path:
    """
    ``<base>/<YYYYMMDD>/<session_tag>/`` for grouped FITS (transit, timelapse, etc.).
    """
    base = ccd_captures_base_dir(ccd_save_dir_setting)
    day = capture_date_folder_name(when)
    slug = slugify_session_tag(session_tag)
    return (base / day / slug).resolve()


def prepare_session_capture_dir(
    ccd_save_dir_setting: str,
    session_tag: str,
    *,
    when: date | None = None,
    dry_run: bool = False,
) -> Path:
    cap = session_capture_dir(ccd_save_dir_setting, session_tag, when=when)
    if not dry_run:
        cap.mkdir(parents=True, exist_ok=True)
    return cap


def fits_filename_hint(
    *,
    session_tag: str,
    frame_index: int,
    exposure_seconds: float,
    filter_name: str = "",
) -> str:
    """
    Suggested filename when the driver allows custom names (documentation / future INDI hook).

    Pattern: ``{session}_{frame:04d}_{exp}s[_{filter}].fits``
    """
    slug = slugify_session_tag(session_tag)
    exp = f"{exposure_seconds:g}".replace(".", "p")
    filt = slugify_session_tag(filter_name) if filter_name else ""
    mid = f"_{filt}" if filt else ""
    return f"{slug}_{frame_index:04d}_{exp}s{mid}.fits"
