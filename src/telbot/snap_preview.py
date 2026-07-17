"""Latest single-snap JPEG preview for the Companion App."""

from __future__ import annotations

import json
from pathlib import Path

from telbot.config import Settings
from telbot.platesolve.security import (
    capture_before_state,
    exposure_capture_search_dirs,
    fits_files_in_dir,
    newest_fits_after_mtime_ns,
    resolve_new_capture_fits_in_dirs,
)
from telbot.repo_paths import snap_last_meta_path, snap_preview_jpeg_path

# Back-compat alias for tests / imports
from telbot.platesolve.security import resolve_new_capture_fits

resolve_new_snap_fits = resolve_new_capture_fits


def _write_snap_last_meta(
    *,
    fits_path: Path | None,
    preview_ok: bool,
    preview_error: str | None = None,
) -> None:
    path = snap_last_meta_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fits_path": str(fits_path) if fits_path is not None else None,
        "preview_ok": preview_ok,
        "preview_error": preview_error,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _encode_preview_jpeg(fits_path: Path, s: Settings) -> bool:
    from telbot.live_stack.fits_io import read_fits_data, write_preview_jpeg

    data = read_fits_data(fits_path)
    write_preview_jpeg(
        snap_preview_jpeg_path(),
        data,
        1,
        max_size=int(s.live_stack_preview_max_px),
    )
    return True


def try_write_snap_preview(
    cap_dir: Path,
    before_mtime_ns: int,
    s: Settings,
    *,
    before_paths: frozenset[Path] | None = None,
    before_state: dict[Path, tuple[int, frozenset[Path]]] | None = None,
) -> tuple[bool, Path | None, str | None]:
    """
    Find FITS from the latest snap and write ``snap_preview.jpg``.

    Returns ``(ok, fits_path, preview_error)``.
    """
    search_dirs = exposure_capture_search_dirs(cap_dir)
    if before_state is None:
        before_state = capture_before_state(search_dirs)
        if before_paths is not None:
            before_state = dict(before_state)
            before_state[cap_dir.resolve()] = (before_mtime_ns, before_paths)
    new_fits = resolve_new_capture_fits_in_dirs(
        search_dirs,
        before_state,
        retry_attempts=20,
        retry_delay_seconds=0.5,
    )
    if new_fits is None:
        _write_snap_last_meta(fits_path=None, preview_ok=False, preview_error="no_new_fits")
        return False, None, "no_new_fits"
    try:
        ok = _encode_preview_jpeg(new_fits, s)
    except (RuntimeError, ValueError, OSError):
        _write_snap_last_meta(
            fits_path=new_fits,
            preview_ok=False,
            preview_error="preview_encode_failed",
        )
        return False, new_fits, "preview_encode_failed"
    _write_snap_last_meta(fits_path=new_fits, preview_ok=True, preview_error=None)
    return ok, new_fits, None


def _fits_from_last_meta() -> Path | None:
    meta_path = snap_last_meta_path()
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw = meta.get("fits_path")
    if not isinstance(raw, str) or not raw.strip():
        return None
    p = Path(raw)
    return p if p.is_file() else None


def ensure_snap_preview_jpeg(s: Settings) -> tuple[Path | None, str]:
    """
    Return ``(jpeg_path, user_message)`` — regenerate from last FITS when JPEG missing.
    """
    jpeg = snap_preview_jpeg_path()
    if jpeg.is_file():
        return jpeg, ""

    fits = _fits_from_last_meta()
    if fits is None:
        from telbot.ccd_paths import effective_ccd_save_dir

        cap = effective_ccd_save_dir(s.ccd_save_dir)
        fits = resolve_new_capture_fits(cap, 0, frozenset(), snap_grace_seconds=600.0)
        if fits is None:
            fits = newest_fits_after_mtime_ns(cap, 0)

    if fits is None:
        return None, "尚无单张预览，请先完成一次 snap 曝光。"

    try:
        _encode_preview_jpeg(fits, s)
    except RuntimeError:
        return (
            None,
            "无法将 FITS 转为 JPEG。请在 Pi 执行：pip install -e \".[livestack]\" 后重启 telbot serve。",
        )
    except (ValueError, OSError) as e:
        return None, f"预览生成失败：{e}"

    if jpeg.is_file():
        _write_snap_last_meta(fits_path=fits, preview_ok=True, preview_error=None)
        return jpeg, ""
    return None, "预览文件写入失败，请查看 Pi 上 data/run 目录权限。"
