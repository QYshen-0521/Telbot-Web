"""Run ASTAP CLI and read WCS from solved FITS."""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

from telbot.config import Settings


def _require_astropy() -> tuple[Any, Any]:
    try:
        from astropy.io import fits
        from astropy.wcs import WCS
    except ImportError as e:
        raise ImportError(
            "plate solve 需要 astropy：pip install -e '.[platesolve]'（或 dev 依赖已含）"
        ) from e
    return fits, WCS


def extract_solution_from_fits(solved_fits: Path) -> dict[str, Any] | None:
    """Return center RA/Dec (deg, ICRS-style from WCS), pixel scale (arcsec/pix), rotation (deg)."""
    fits, WCS = _require_astropy()
    try:
        h = fits.getheader(str(solved_fits), ext=0)
    except OSError:
        return None
    if "CRVAL1" not in h or "CRVAL2" not in h:
        return None
    try:
        wcs = WCS(h)
    except Exception:
        return None
    if not wcs.has_celestial:
        return None
    naxis1 = int(h.get("NAXIS1", 0) or 0)
    naxis2 = int(h.get("NAXIS2", 0) or 0)
    if naxis1 > 0 and naxis2 > 0:
        xc = (1.0 + naxis1) / 2.0
        yc = (1.0 + naxis2) / 2.0
    else:
        xc, yc = 1.0, 1.0
    try:
        sky = wcs.pixel_to_world(xc, yc)
        ra_deg = float(sky.ra.deg)
        dec_deg = float(sky.dec.deg)
    except Exception:
        try:
            vals = wcs.pixel_to_world_values(xc, yc)
            ra_deg = float(vals[0])
            dec_deg = float(vals[1])
        except Exception:
            return None
    try:
        from astropy import units as u
        from astropy.wcs.utils import proj_plane_pixel_scales

        scales = proj_plane_pixel_scales(wcs)
        px_scale = float(
            (scales[0].to(u.arcsec).value + scales[1].to(u.arcsec).value) / 2.0
        )
    except Exception:
        cd1 = float(h.get("CD1_1", h.get("PC1_1", 0)) or 0)
        cd2 = float(h.get("CD2_1", h.get("PC2_1", 0)) or 0)
        scale_deg = math.sqrt(cd1 * cd1 + cd2 * cd2)
        px_scale = scale_deg * 3600.0
    try:
        m = wcs.pixel_scale_matrix
        rot_deg = math.degrees(math.atan2(float(m[1, 0]), float(m[0, 0])))
    except Exception:
        rot_deg = float(h.get("CROTA2", h.get("CROTA1", 0)) or 0)
    ctype1 = str(h.get("CTYPE1", "RA---TAN"))
    ctype2 = str(h.get("CTYPE2", "DEC--TAN"))
    frame = "ICRS"
    if "FK5" in ctype1.upper() or "FK5" in ctype2.upper():
        frame = "FK5"
    return {
        "ra_icrs_deg": ra_deg,
        "dec_icrs_deg": dec_deg,
        "pixel_scale_arcsec_per_pixel": px_scale,
        "rotation_deg": rot_deg,
        "wcs_ctype1": ctype1,
        "wcs_ctype2": ctype2,
        "frame": frame,
    }


def run_astap(
    s: Settings,
    input_fits: Path,
    work_dir: Path,
    log_path: Path,
) -> tuple[bool, Path | None, str]:
    """
    Copy input into work_dir as input.fits, run ASTAP, return (ok, path_to_solved_fits, combined_log).
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    work_fits = work_dir / "input.fits"
    shutil.copy2(input_fits, work_fits)
    bin_name = (s.platesolve_astap_bin or "astap").strip() or "astap"
    cmd: list[str] = [bin_name, "-f", str(work_fits)]
    db = (s.platesolve_star_database_dir or "").strip()
    if db:
        cmd.extend(["-d", db])
    timeout = max(10.0, float(s.platesolve_timeout_s))
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        log_path.write_text(f"未找到可执行文件：{bin_name}\n", encoding="utf-8")
        return False, None, log_path.read_text(encoding="utf-8")
    except subprocess.TimeoutExpired:
        log_path.write_text(f"ASTAP 超时（{timeout}s）\n", encoding="utf-8")
        return False, None, log_path.read_text(encoding="utf-8")
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    log_path.write_text(combined, encoding="utf-8")
    if proc.returncode != 0:
        return False, None, combined
    sol = extract_solution_from_fits(work_fits)
    if sol is None:
        return False, work_fits, combined + "\n(no WCS in FITS after ASTAP)\n"
    return True, work_fits, combined

