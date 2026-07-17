"""Running sum stack with optional per-frame alignment."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from typing import TYPE_CHECKING

from telbot.live_stack.align import estimate_shift, shift_image
from telbot.live_stack.fits_io import read_fits_data

if TYPE_CHECKING:
    from telbot.calibration_masters import CalibrationMasters


@dataclass
class LiveStackAccumulator:
    """Aligned cumulative average stack."""

    frame_count: int = 0
    _sum: object = field(default=None, repr=False)
    _ref_shape: tuple[int, int] | None = field(default=None, repr=False)
    _calibration: object | None = field(default=None, repr=False)

    def add_frame(
        self,
        fits_path: Path,
        *,
        align: bool = True,
        calibration: CalibrationMasters | None = None,
    ) -> dict:
        data = read_fits_data(fits_path)
        import numpy as np

        calibrated = False
        cal = calibration or self._calibration
        if cal is not None and getattr(cal, "enabled", False):
            data = cal.apply(data)
            calibrated = True

        if self._sum is None:
            self._sum = np.zeros_like(data, dtype=np.float64)
            self._ref_shape = data.shape
            aligned = data
            shift_dy, shift_dx = 0.0, 0.0
        else:
            if data.shape != self._ref_shape:
                raise ValueError(f"帧尺寸变化 {data.shape} vs {self._ref_shape}")
            if align and self.frame_count > 0:
                shift_dy, shift_dx = estimate_shift(self._sum / max(1, self.frame_count), data)
                aligned = shift_image(data, shift_dy, shift_dx)
            else:
                shift_dy, shift_dx = 0.0, 0.0
                aligned = data
        self._sum += np.asarray(aligned, dtype=np.float64)
        self.frame_count += 1
        return {
            "frame_index": self.frame_count,
            "fits": str(fits_path),
            "shift_dy": shift_dy,
            "shift_dx": shift_dx,
            "calibrated": calibrated,
        }

    @property
    def sum_array(self):
        if self._sum is None:
            raise RuntimeError("尚无叠加帧")
        return self._sum
