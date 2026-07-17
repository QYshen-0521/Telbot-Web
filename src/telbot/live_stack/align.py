"""Frame-to-frame translation alignment (phase correlation)."""

from __future__ import annotations


def estimate_shift(ref, target) -> tuple[float, float]:
    """
    Estimate shift (dy, dx) to apply to *target* to align with *ref*.

    Uses FFT phase correlation on downsampled images for speed.
    """
    from telbot.live_stack.fits_io import require_live_stack_deps

    require_live_stack_deps()
    import numpy as np

    a = np.asarray(ref, dtype=np.float32)
    b = np.asarray(target, dtype=np.float32)
    if a.shape != b.shape:
        raise ValueError(f"shape mismatch {a.shape} vs {b.shape}")

    max_side = 512
    h, w = a.shape
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        step = int(round(1.0 / scale))
        a = a[::step, ::step]
        b = b[::step, ::step]

    a = a - float(np.median(a))
    b = b - float(np.median(b))
    fa = np.fft.fft2(a)
    fb = np.fft.fft2(b)
    cross = fa * np.conj(fb)
    denom = np.abs(cross)
    denom[denom < 1e-12] = 1e-12
    cross /= denom
    cc = np.fft.ifft2(cross)
    cc = np.real(cc)
    peak = np.unravel_index(int(np.argmax(cc)), cc.shape)
    dy = float(peak[0])
    dx = float(peak[1])
    if dy > cc.shape[0] / 2:
        dy -= cc.shape[0]
    if dx > cc.shape[1] / 2:
        dx -= cc.shape[1]
    if scale < 1.0:
        inv = 1.0 / scale
        dy *= inv
        dx *= inv
    return dy, dx


def shift_image(img, dy: float, dx: float):
    """Shift *img* by (dy, dx) with zero padding (integer-rounded)."""
    import numpy as np

    arr = np.asarray(img, dtype=np.float32)
    iy = int(round(dy))
    ix = int(round(dx))
    out = np.zeros_like(arr)
    h, w = arr.shape

    src_y0 = max(0, -iy)
    src_y1 = min(h, h - iy)
    src_x0 = max(0, -ix)
    src_x1 = min(w, w - ix)
    dst_y0 = max(0, iy)
    dst_x0 = max(0, ix)
    dst_y1 = dst_y0 + (src_y1 - src_y0)
    dst_x1 = dst_x0 + (src_x1 - src_x0)
    if src_y1 <= src_y0 or src_x1 <= src_x0:
        return out
    out[dst_y0:dst_y1, dst_x0:dst_x1] = arr[src_y0:src_y1, src_x0:src_x1]
    return out
