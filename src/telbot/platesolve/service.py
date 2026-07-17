"""Orchestrate staging, ASTAP, JNow conversion, last_solve.json."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from skyfield.api import wgs84
from skyfield.starlib import Star

from telbot.skyfield_data import get_skyfield_loader

from telbot.ccd_paths import ccd_captures_base_dir, effective_ccd_save_dir
from telbot.config import Settings
from telbot.platesolve.astap_backend import extract_solution_from_fits, run_astap
from telbot.platesolve.security import (
    allowed_fits_roots,
    find_latest_fits_in_dir,
    find_latest_fits_under_tree,
    resolve_and_check_fits_path,
)
from telbot.repo_paths import (
    ensure_platesolve_layout,
    platesolve_last_solve_json,
    platesolve_logs_dir,
    platesolve_out_dir,
    platesolve_in_dir,
)


def _jnow_from_icrs(ra_deg: float, dec_deg: float, s: Settings) -> tuple[float | None, float | None]:
    if abs(s.latitude) < 1e-12 and abs(s.longitude) < 1e-12:
        return None, None
    try:
        ts = get_skyfield_loader().timescale()
        t = ts.now()
        earth = wgs84.latlon(s.latitude, s.longitude, s.elevation_m)
        star = Star(ra_hours=ra_deg / 15.0, dec_degrees=dec_deg)
        app = earth.at(t).observe(star)
        ra_h, dec_d, _ = app.radec()
        return float(ra_h.hours), float(dec_d.degrees)
    except Exception:
        return None, None


def run_platesolve(
    s: Settings,
    *,
    fits_path: Path | None,
    use_latest: bool,
) -> dict[str, Any]:
    ensure_platesolve_layout()
    if use_latest:
        cap_today = effective_ccd_save_dir(s.ccd_save_dir)
        src = find_latest_fits_in_dir(cap_today)
        if src is None:
            base = ccd_captures_base_dir(s.ccd_save_dir)
            src = find_latest_fits_under_tree(base)
        if src is None:
            raise RuntimeError(f"目录中未找到 .fits：{cap_today} 或 {base}")
    elif fits_path is not None:
        src = resolve_and_check_fits_path(str(fits_path), s)
    else:
        raise RuntimeError("内部错误：未指定 fits_path 或 use_latest")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    staging = platesolve_in_dir() / f"{stamp}_{src.name}"
    shutil.copy2(src, staging)

    work = platesolve_out_dir() / f"run_{stamp}"
    log_p = platesolve_logs_dir() / f"astap_{stamp}.log"

    if (s.platesolve_backend or "astap").strip().lower() != "astap":
        raise RuntimeError(f"暂不支持的 platesolve backend：{s.platesolve_backend}")

    ok, solved_fits, log_text = run_astap(s, staging, work, log_p)
    out: dict[str, Any] = {
        "ok": ok,
        "backend": "astap",
        "input_fits": str(src.resolve()),
        "staging_fits": str(staging.resolve()),
        "work_dir": str(work.resolve()),
        "solver_log_path": str(log_p.resolve()),
    }
    if solved_fits is not None:
        out["wcs_fits_path"] = str(solved_fits.resolve())
    if not ok:
        out["message"] = "ASTAP 失败或未得到 WCS"
        json_path = platesolve_last_solve_json()
        json_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        out["last_solve_json"] = str(json_path.resolve())
        return out

    sol = extract_solution_from_fits(solved_fits)
    if sol is None:
        out["ok"] = False
        out["message"] = "ASTAP 退出成功但 FITS 无 WCS"
        json_path = platesolve_last_solve_json()
        json_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        out["last_solve_json"] = str(json_path.resolve())
        return out

    ra_d = sol["ra_icrs_deg"]
    dec_d = sol["dec_icrs_deg"]
    j_ra, j_dec = _jnow_from_icrs(ra_d, dec_d, s)
    out.update(
        {
            "ra_icrs_deg": ra_d,
            "dec_icrs_deg": dec_d,
            "pixel_scale_arcsec_per_pixel": sol["pixel_scale_arcsec_per_pixel"],
            "rotation_deg": sol["rotation_deg"],
            "wcs_ctype1": sol["wcs_ctype1"],
            "wcs_ctype2": sol["wcs_ctype2"],
            "frame": sol["frame"],
        }
    )
    if j_ra is not None and j_dec is not None:
        out["jnow_ra_hours"] = j_ra
        out["jnow_dec_deg"] = j_dec
    out["message"] = "ok"
    json_path = platesolve_last_solve_json()
    json_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    out["last_solve_json"] = str(json_path.resolve())
    out["allowed_roots"] = [str(p) for p in allowed_fits_roots(s)]
    return out
