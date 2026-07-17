"""FITS read/write and preview JPEG for live stack."""

from __future__ import annotations

from pathlib import Path


def require_fits_deps() -> None:
    """FITS 读写与校准合成（astropy + numpy）。"""
    try:
        import astropy  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "FITS 处理需要可选依赖：pip install -e \".[livestack]\"（至少 astropy）"
        ) from e


def require_live_stack_deps() -> None:
    require_fits_deps()
    try:
        from PIL import Image  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "边拍边叠需要可选依赖：pip install -e \".[livestack]\"（astropy + pillow）"
        ) from e


def read_fits_data(path: Path):
    require_fits_deps()
    from astropy.io import fits

    # QHY 等驱动常带 BZERO/BSCALE/BLANK；memmap=True 时 astropy 会拒绝加载。
    with fits.open(path, memmap=False) as hdul:
        data = hdul[0].data
    if data is None:
        raise ValueError(f"FITS 无图像数据：{path}")
    import numpy as np

    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim == 3:
        arr = arr[0]
    if arr.ndim != 2:
        raise ValueError(f"不支持的 FITS 维度 {arr.ndim}：{path}")
    return arr


def write_fits_stack(path: Path, stack_sum, frame_count: int) -> None:
    require_live_stack_deps()
    from astropy.io import fits
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    avg = (stack_sum / max(1, frame_count)).astype(np.float32)
    hdu = fits.PrimaryHDU(avg)
    hdu.header["LSTACK_N"] = (int(frame_count), "frames in live stack")
    hdu.writeto(path, overwrite=True)


def write_preview_jpeg(path: Path, stack_sum, frame_count: int, *, max_size: int = 1024) -> None:
    require_live_stack_deps()
    import numpy as np
    from PIL import Image

    if frame_count <= 0:
        raise ValueError("frame_count 须 > 0")
    avg = stack_sum / float(frame_count)
    lo, hi = np.percentile(avg, (1.0, 99.5))
    span = max(hi - lo, 1e-6)
    u8 = np.clip((avg - lo) / span * 255.0, 0, 255).astype(np.uint8)
    img = Image.fromarray(u8, mode="L")
    w, h = img.size
    scale = min(1.0, max_size / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="JPEG", quality=85, optimize=True)
