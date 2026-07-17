"""Live-stack session directories (raw FITS retained)."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telbot.fits_session import prepare_session_capture_dir, slugify_session_tag


def live_stack_session_root(ccd_save_dir: str, session_tag: str) -> Path:
    """``<captures>/<YYYYMMDD>/<session_tag>/`` with ``raw/``, ``stack/``, ``preview/``."""
    base = prepare_session_capture_dir(ccd_save_dir, session_tag, dry_run=False)
    for sub in ("raw", "stack", "preview"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def archive_raw_frame(src: Path, raw_dir: Path, frame_index: int) -> Path:
    """Copy driver FITS into ``raw/frame_NNNN.fits`` (keeps original upload name file too)."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / f"frame_{frame_index:04d}.fits"
    shutil.copy2(src, dest)
    return dest


def write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_session_tag() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return slugify_session_tag(f"livestack_{stamp}")
