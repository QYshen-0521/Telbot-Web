"""Master calibration frames (bias/dark/flat) for live stacking and processing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_CALIB_KINDS = ("bias", "dark", "flat")


def _require_numpy():
    from telbot.live_stack.fits_io import require_fits_deps

    require_fits_deps()
    import numpy as np

    return np


def list_calibration_fits(directory: Path, kind: str | None = None) -> list[Path]:
    """
    FITS under *directory* (non-recursive), sorted by name.

    优先 ``{kind}_*.fits`` 归档名；排除 INDI 临时 ``IMAGE_*.fits``。
    仍兼容旧版 ``cal_<kind>_*/`` 目录内的 ``bias_0001_0s.fits`` 等（匹配 ``{kind}_`` 前缀）。
    """
    if not directory.is_dir():
        return []
    out: list[Path] = []
    for pattern in ("*.fits", "*.fit", "*.fts", "*.FITS", "*.FIT", "*.FTS"):
        out.extend(p for p in directory.glob(pattern) if p.is_file())
    resolved = sorted({p.resolve() for p in out})
    if kind:
        prefixed = [p for p in resolved if p.name.startswith(f"{kind}_")]
        if prefixed:
            return prefixed
    return [
        p
        for p in resolved
        if not p.name.upper().startswith("IMAGE")
    ]


def median_master_from_dir(directory: Path, *, min_frames: int = 1) -> Any:
    """Median combine all FITS in a calibration session directory."""
    from telbot.live_stack.fits_io import read_fits_data

    np = _require_numpy()
    kind_hint = directory.name.split("_", 1)[0] if "_" in directory.name else None
    if kind_hint not in _CALIB_KINDS:
        kind_hint = None
    paths = list_calibration_fits(directory, kind=kind_hint)
    if len(paths) < min_frames:
        raise ValueError(
            f"目录 {directory} 中 FITS 不足（找到 {len(paths)}，需要至少 {min_frames}）"
        )
    layers = [np.asarray(read_fits_data(p), dtype=np.float64) for p in paths]
    return np.median(np.stack(layers, axis=0), axis=0)


@dataclass
class CalibrationMasters:
    """
    Master bias / dark / flat for per-light calibration before live stack.

    Pipeline (when all provided): ``cal = (light - bias - dark) / flat_norm``
    where *dark* is bias-subtracted median dark, *flat_norm* is bias-subtracted
    flat divided by its median.
    """

    bias: Any | None = None
    dark: Any | None = None
    flat: Any | None = None
    bias_dir: str | None = None
    dark_dir: str | None = None
    flat_dir: str | None = None
    _flat_norm: Any | None = field(default=None, repr=False)

    @property
    def enabled(self) -> bool:
        return self.bias is not None or self.dark is not None or self.flat is not None

    @classmethod
    def from_directories(
        cls,
        *,
        bias_dir: str | Path | None = None,
        dark_dir: str | Path | None = None,
        flat_dir: str | Path | None = None,
        min_frames: int = 1,
    ) -> CalibrationMasters:
        """Build masters from ``telbot camera cal`` session folders."""
        np = _require_numpy()
        masters = cls()
        if bias_dir:
            p = Path(bias_dir).expanduser().resolve()
            masters.bias = median_master_from_dir(p, min_frames=min_frames)
            masters.bias_dir = str(p)
        if dark_dir:
            p = Path(dark_dir).expanduser().resolve()
            raw_dark = median_master_from_dir(p, min_frames=min_frames)
            if masters.bias is not None:
                masters.dark = raw_dark - masters.bias
            else:
                masters.dark = raw_dark
            masters.dark_dir = str(p)
        if flat_dir:
            p = Path(flat_dir).expanduser().resolve()
            raw_flat = median_master_from_dir(p, min_frames=min_frames)
            if masters.bias is not None:
                raw_flat = raw_flat - masters.bias
            med = float(np.median(raw_flat))
            masters._flat_norm = raw_flat / max(med, 1e-6)
            masters.flat = masters._flat_norm
            masters.flat_dir = str(p)
        return masters

    @classmethod
    def from_settings(cls, s) -> CalibrationMasters:
        """Load paths from ``TELBOT_LIVE_STACK_CAL_*_DIR`` when set."""
        bias = (getattr(s, "live_stack_cal_bias_dir", None) or "").strip()
        dark = (getattr(s, "live_stack_cal_dark_dir", None) or "").strip()
        flat = (getattr(s, "live_stack_cal_flat_dir", None) or "").strip()
        if not bias and not dark and not flat:
            return cls()
        return cls.from_directories(
            bias_dir=bias or None,
            dark_dir=dark or None,
            flat_dir=flat or None,
        )

    def _match_shape(self, light: Any, master: Any, label: str) -> Any:
        if light.shape == master.shape:
            return master
        raise ValueError(
            f"校准帧 {label} 尺寸 {master.shape} 与亮场 {light.shape} 不一致；"
            "请用相同 bin/ROI 拍摄校准帧与 live-stack"
        )

    def apply(self, light: Any) -> Any:
        """Return bias/dark/flat-corrected light frame (float64)."""
        if not self.enabled:
            return light
        np = _require_numpy()
        out = np.asarray(light, dtype=np.float64)
        if self.bias is not None:
            b = self._match_shape(out, self.bias, "bias")
            out = out - b
        if self.dark is not None:
            d = self._match_shape(out, self.dark, "dark")
            out = out - d
        if self._flat_norm is not None:
            f = self._match_shape(out, self._flat_norm, "flat")
            out = out / np.maximum(f, 1e-3)
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "bias_dir": self.bias_dir,
            "dark_dir": self.dark_dir,
            "flat_dir": self.flat_dir,
            "has_bias": self.bias is not None,
            "has_dark": self.dark is not None,
            "has_flat": self.flat is not None,
        }


def write_masters_fits(dest_dir: Path, masters: CalibrationMasters) -> list[str]:
    """Write master_bias/dark/flat.fits into *dest_dir* for inspection."""
    from telbot.live_stack.fits_io import require_fits_deps

    require_fits_deps()
    from astropy.io import fits

    dest_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, arr in (
        ("master_bias", masters.bias),
        ("master_dark", masters.dark),
        ("master_flat", masters._flat_norm if masters._flat_norm is not None else masters.flat),
    ):
        if arr is None:
            continue
        path = dest_dir / f"{name}.fits"
        fits.PrimaryHDU(arr.astype("float32")).writeto(path, overwrite=True)
        written.append(str(path))
    return written
