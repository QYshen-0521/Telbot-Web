"""Median HFR (half-flux radius) from a FITS image — autofocus sharpness metric."""

from __future__ import annotations

from pathlib import Path


def _require_numpy():
    try:
        import numpy as np

        return np
    except ImportError as e:
        raise RuntimeError(
            "自动对焦需要 astropy/numpy：pip install -e \".[autofocus]\" 或 \".[platesolve]\""
        ) from e


def _hfr_on_patch(patch) -> float | None:
    np = _require_numpy()
    patch = np.asarray(patch, dtype=np.float64)
    bg = float(np.median(patch))
    patch = patch - bg
    patch[patch < 0] = 0.0
    total = float(patch.sum())
    if total <= 0:
        return None
    cy, cx = np.unravel_index(int(np.argmax(patch)), patch.shape)
    yy, xx = np.ogrid[: patch.shape[0], : patch.shape[1]]
    r = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    flat_r = r.ravel()
    flat_flux = patch.ravel()
    order = np.argsort(flat_r)
    cum = np.cumsum(flat_flux[order])
    half = total * 0.5
    idx = int(np.searchsorted(cum, half))
    if idx >= len(order):
        return None
    return float(flat_r[order][idx])


def _local_maxima(data, *, min_sep: int, thresh: float) -> list[tuple[int, int]]:
    np = _require_numpy()
    h, w = data.shape
    peaks: list[tuple[int, int]] = []
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            v = data[y, x]
            if v < thresh:
                continue
            nb = data[y - 1 : y + 2, x - 1 : x + 2]
            if v < nb.max():
                continue
            if any(abs(y - py) < min_sep and abs(x - px) < min_sep for py, px in peaks):
                continue
            peaks.append((y, x))
    peaks.sort(key=lambda p: data[p[0], p[1]], reverse=True)
    return peaks


def compute_median_hfr(fits_path: Path, *, patch_radius: int = 16) -> tuple[float | None, int]:
    """
    Return (median HFR in pixels, star count used).

    Uses brightest local maxima in the central 70% of the frame.
    """
    try:
        from astropy.io import fits
    except ImportError as e:
        raise RuntimeError(
            "自动对焦需要 astropy：pip install -e \".[autofocus]\" 或 \".[platesolve]\""
        ) from e

    np = _require_numpy()
    with fits.open(fits_path, memmap=False) as hdul:
        data = hdul[0].data
    if data is None:
        return None, 0
    data = np.asarray(data, dtype=np.float64)
    if data.ndim > 2:
        data = data[0]

    h, w = data.shape
    margin_y = int(h * 0.15)
    margin_x = int(w * 0.15)
    roi = data[margin_y : h - margin_y, margin_x : w - margin_x]
    if roi.size == 0:
        roi = data

    bg = float(np.median(roi))
    sub = roi - bg
    std = float(np.std(sub))
    if std <= 0:
        return None, 0
    thresh = max(std * 4.0, float(np.percentile(sub[sub > 0], 99)) * 0.2 if np.any(sub > 0) else std * 5)

    peaks = _local_maxima(sub, min_sep=max(8, patch_radius // 2), thresh=thresh)
    if not peaks:
        return _hfr_on_patch(sub), 1 if _hfr_on_patch(sub) is not None else 0

    hfrs: list[float] = []
    pr = patch_radius
    rh, rw = sub.shape
    for y, x in peaks[:12]:
        y0 = max(0, y - pr)
        y1 = min(rh, y + pr + 1)
        x0 = max(0, x - pr)
        x1 = min(rw, x + pr + 1)
        hfr = _hfr_on_patch(sub[y0:y1, x0:x1])
        if hfr is not None and hfr > 0:
            hfrs.append(hfr)
    if not hfrs:
        return None, 0
    return float(np.median(hfrs)), len(hfrs)
