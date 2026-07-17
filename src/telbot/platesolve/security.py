"""Restrict FITS paths to known capture/staging roots (anti path traversal)."""

from __future__ import annotations

import time
from pathlib import Path

_FITS_GLOBS = ("*.fits", "*.fit", "*.fts", "*.FITS", "*.FIT", "*.FTS")
_INDI_DRIVER_GLOBS = ("IMAGE_*.fits", "IMAGE_*.FITS", "IMAGE_*.fit", "IMAGE_*.FIT")

from telbot.ccd_paths import ccd_captures_base_dir
from telbot.config import Settings
from telbot.repo_paths import platesolve_in_dir, telbot_repo_root


def allowed_fits_roots(s: Settings) -> list[Path]:
    roots = [
        ccd_captures_base_dir(s.ccd_save_dir),
        platesolve_in_dir().resolve(),
    ]
    # de-dupe while preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        k = str(r.resolve())
        if k not in seen:
            seen.add(k)
            out.append(r.resolve())
    return out


def resolve_and_check_fits_path(path_str: str, s: Settings) -> Path:
    """Return resolved file path or raise ValueError."""
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = (telbot_repo_root() / p).resolve()
    else:
        p = p.resolve()
    if not p.is_file():
        raise ValueError(f"不是可读文件：{p}")
    suffix = p.suffix.lower()
    if suffix not in (".fits", ".fit", ".fts"):
        raise ValueError("需要 .fits / .fit / .fts")
    for root in allowed_fits_roots(s):
        try:
            p.relative_to(root)
            return p
        except ValueError:
            continue
    raise ValueError(f"路径不在允许目录内（CCD 保存或 data/platesolve/in）：{p}")


def fits_files_in_dir(d: Path) -> frozenset[Path]:
    """Resolved paths of FITS files in *d* (non-recursive)."""
    if not d.is_dir():
        return frozenset()
    found: set[Path] = set()
    for pattern in _FITS_GLOBS:
        for f in d.glob(pattern):
            if f.is_file():
                found.add(f.resolve())
    return frozenset(found)


def _resolve_new_capture_fits_once(
    cap_dir: Path,
    before_mtime_ns: int,
    before_paths: frozenset[Path],
    *,
    snap_grace_seconds: float = 180.0,
) -> Path | None:
    """
    Locate the FITS from an exposure that just finished.

    1. Path set difference (new ``IMAGE_002.fits`` after ``IMAGE_001``).
    2. ``mtime_ns > before_mtime_ns`` (any filename).
    3. INDI overwrites same ``IMAGE_001.fits`` (path already in *before_paths*, mtime grew).
    4. Newest file under *cap_dir* modified within *snap_grace_seconds*.
    """
    after_paths = fits_files_in_dir(cap_dir)
    added = after_paths - before_paths
    if added:
        return max(added, key=lambda p: p.stat().st_mtime_ns)

    candidate = newest_fits_after_mtime_ns(cap_dir, before_mtime_ns)
    if candidate is not None:
        return candidate.resolve()

    best_driver: Path | None = None
    best_driver_ns = before_mtime_ns
    for pattern in _INDI_DRIVER_GLOBS:
        for p in cap_dir.glob(pattern):
            if not p.is_file():
                continue
            ns = p.stat().st_mtime_ns
            if ns > best_driver_ns:
                best_driver_ns = ns
                best_driver = p
    if best_driver is not None:
        return best_driver.resolve()

    now_ns = time.time_ns()
    grace_ns = int(snap_grace_seconds * 1_000_000_000)
    best: Path | None = None
    best_ns = 0
    for p in after_paths:
        ns = p.stat().st_mtime_ns
        if now_ns - ns <= grace_ns and ns >= best_ns:
            best_ns = ns
            best = p
    return best.resolve() if best is not None else None


def exposure_capture_search_dirs(cap_dir: Path) -> list[Path]:
    """
    Directories to scan after CCD upload.

    INDI 有时将 ``IMAGE_*.fits`` 写在 ``YYYYMMDD/`` 根下，而非 ``YYYYMMDD/bias_<session>/`` 等子目录。
    """
    ordered: list[Path] = []
    seen: set[str] = set()
    for d in (cap_dir, cap_dir.parent):
        try:
            resolved = d.resolve()
        except OSError:
            continue
        key = str(resolved)
        if key in seen or not resolved.is_dir():
            continue
        seen.add(key)
        ordered.append(resolved)
    return ordered


def capture_before_state(dirs: list[Path]) -> dict[Path, tuple[int, frozenset[Path]]]:
    return {d: (max_fits_mtime_ns_in_dir(d), fits_files_in_dir(d)) for d in dirs}


def resolve_new_capture_fits(
    cap_dir: Path,
    before_mtime_ns: int,
    before_paths: frozenset[Path],
    *,
    snap_grace_seconds: float = 180.0,
    retry_attempts: int = 10,
    retry_delay_seconds: float = 0.35,
) -> Path | None:
    """Like ``_resolve_new_capture_fits_once`` with short retries (driver write latency)."""
    last: Path | None = None
    for attempt in range(max(1, retry_attempts)):
        last = _resolve_new_capture_fits_once(
            cap_dir,
            before_mtime_ns,
            before_paths,
            snap_grace_seconds=snap_grace_seconds,
        )
        if last is not None:
            return last
        if attempt < retry_attempts - 1:
            time.sleep(retry_delay_seconds)
    return None


def resolve_new_capture_fits_in_dirs(
    dirs: list[Path],
    before_state: dict[Path, tuple[int, frozenset[Path]]],
    *,
    snap_grace_seconds: float = 180.0,
    retry_attempts: int = 10,
    retry_delay_seconds: float = 0.35,
) -> Path | None:
    """Try each directory (session folder, then ``YYYYMMDD`` parent)."""
    for d in dirs:
        before_ns, before_paths = before_state.get(d, (0, frozenset()))
        found = resolve_new_capture_fits(
            d,
            before_ns,
            before_paths,
            snap_grace_seconds=snap_grace_seconds,
            retry_attempts=retry_attempts,
            retry_delay_seconds=retry_delay_seconds,
        )
        if found is not None:
            return found
    return None


def fits_probe_for_dirs(dirs: list[Path]) -> dict[str, list[str]]:
    """Diagnostic: FITS basenames per directory (for API error messages)."""
    out: dict[str, list[str]] = {}
    for d in dirs:
        out[str(d)] = sorted(p.name for p in fits_files_in_dir(d))
    return out


def find_latest_fits_in_dir(d: Path) -> Path | None:
    if not d.is_dir():
        return None
    candidates: list[Path] = []
    for pattern in _FITS_GLOBS:
        candidates.extend(d.glob(pattern))
    if not candidates:
        return None
    return max(candidates, key=lambda x: x.stat().st_mtime)


def max_fits_mtime_ns_in_dir(d: Path) -> int:
    """Largest st_mtime_ns among FITS under d; 0 if none or d missing."""
    if not d.is_dir():
        return 0
    mx = 0
    for pattern in _FITS_GLOBS:
        for f in d.glob(pattern):
            if f.is_file():
                mx = max(mx, f.stat().st_mtime_ns)
    return mx


def find_latest_fits_under_tree(root: Path) -> Path | None:
    """Newest FITS under *root* recursively (any ``YYYYMMDD`` subfolder)."""
    if not root.is_dir():
        return None
    best: Path | None = None
    best_ns = 0
    for pattern in _FITS_GLOBS:
        for f in root.rglob(pattern):
            if not f.is_file():
                continue
            ns = f.stat().st_mtime_ns
            if ns > best_ns:
                best_ns = ns
                best = f
    return best


def newest_fits_after_mtime_ns(d: Path, since_ns: int) -> Path | None:
    """Newest FITS strictly newer than since_ns (by mtime_ns); None if none."""
    if not d.is_dir():
        return None
    best: Path | None = None
    best_ns = since_ns
    for pattern in _FITS_GLOBS:
        for f in d.glob(pattern):
            if not f.is_file():
                continue
            ns = f.stat().st_mtime_ns
            if ns > best_ns:
                best_ns = ns
                best = f
    return best
