"""
Ground-based exoplanet transit exposure time calculator (ETC).

Estimates per-frame exposure from host V magnitude, transit depth, and a
configurable instrument model (aperture, focal length, pixel size, noise).
"""

from __future__ import annotations

import math
from typing import Any

from telbot.config import Settings
from telbot.planning.transit_etc_instrument import (
    ResolvedEtcInstrument,
    instrument_dict_for_etc,
    resolve_transit_etc_instrument,
)

ETC_SCHEMA_VERSION = "telbot.transit_etc.v1"


def _plate_scale_arcsec_per_pixel(focal_length_mm: float, pixel_size_um: float) -> float:
    if focal_length_mm <= 0 or pixel_size_um <= 0:
        raise ValueError("焦距与像素尺寸须 > 0")
    return 206.265 * pixel_size_um / focal_length_mm


def _star_electrons_per_second(
    vmag: float,
    aperture_m: float,
    throughput: float,
    flux_cal_e_per_s_v0_at_1m: float,
) -> float:
    """
    Calibrated stellar signal rate (electrons/s) at detector.

    rate = flux_cal * 10^(-0.4*V) * D_m^2 * throughput
    """
    if vmag < 0 or aperture_m <= 0 or throughput <= 0:
        raise ValueError("vmag、口径、throughput 须为正")
    return flux_cal_e_per_s_v0_at_1m * (10 ** (-0.4 * vmag)) * (aperture_m**2) * throughput


def _sky_electrons_per_pixel_per_second(
    sky_mag_per_arcsec2: float,
    plate_scale_arcsec_per_pix: float,
    aperture_m: float,
    throughput: float,
    flux_cal_e_per_s_v0_at_1m: float,
) -> float:
    """Sky background rate per pixel (electrons/s/pix), same flux calibration as star."""
    if plate_scale_arcsec_per_pix <= 0:
        raise ValueError("plate scale 须 > 0")
    pixel_area_arcsec2 = plate_scale_arcsec_per_pix**2
    # Sky as extended source: rate scales with pixel solid angle and collecting area
    return (
        flux_cal_e_per_s_v0_at_1m
        * (10 ** (-0.4 * sky_mag_per_arcsec2))
        * pixel_area_arcsec2
        * (aperture_m**2)
        * throughput
        * 0.25
    )


def _aperture_pixels(radius_pix: float) -> float:
    return math.pi * max(radius_pix, 0.5) ** 2


def _photometry_snr(
    t_seconds: float,
    *,
    star_e_per_s: float,
    sky_e_per_pix_per_s: float,
    n_pix: float,
    read_noise_e: float,
) -> float:
    s = star_e_per_s * t_seconds
    b = sky_e_per_pix_per_s * n_pix * t_seconds
    var = s + b + (read_noise_e**2) * n_pix
    if var <= 0:
        return 0.0
    return s / math.sqrt(var)


def _exposure_for_depth_snr(
    depth_fraction: float,
    target_snr_on_depth: float,
    *,
    star_e_per_s: float,
    sky_e_per_pix_per_s: float,
    n_pix: float,
    read_noise_e: float,
    t_min: float,
    t_max: float,
) -> float:
    """
    Choose t so photometric SNR(star) >= target_snr_on_depth / depth_fraction.

    Relative flux precision ~ 1/SNR; detecting depth δ needs SNR_star ≳ k/δ.
    """
    if depth_fraction <= 0:
        depth_fraction = 0.001
    need_snr = target_snr_on_depth / depth_fraction
    lo, hi = t_min, t_max
    if _photometry_snr(lo, star_e_per_s=star_e_per_s, sky_e_per_pix_per_s=sky_e_per_pix_per_s,
                       n_pix=n_pix, read_noise_e=read_noise_e) >= need_snr:
        return lo
    for _ in range(48):
        mid = (lo + hi) / 2.0
        if _photometry_snr(
            mid,
            star_e_per_s=star_e_per_s,
            sky_e_per_pix_per_s=sky_e_per_pix_per_s,
            n_pix=n_pix,
            read_noise_e=read_noise_e,
        ) >= need_snr:
            hi = mid
        else:
            lo = mid
    return hi


def _saturation_limited_exposure(
    star_e_per_s: float,
    *,
    full_well_e: float,
    peak_fraction: float,
    effective_n_pix: float,
) -> float:
    """Max exposure before peak electrons in stellar core reach full well."""
    if star_e_per_s <= 0 or effective_n_pix <= 0:
        return float("inf")
    peak_rate = star_e_per_s / effective_n_pix
    if peak_rate <= 0:
        return float("inf")
    return peak_fraction * full_well_e / peak_rate


def _quantize_exposure(t: float, step: float) -> float:
    if step <= 0:
        return round(t, 3)
    return max(step, round(t / step) * step)


def compute_transit_exposure(
    s: Settings,
    event: dict[str, Any],
    *,
    airmass: float = 1.0,
    instrument: ResolvedEtcInstrument | None = None,
    planning_only: bool = False,
) -> dict[str, Any]:
    """
    Compute recommended science exposure (seconds) and diagnostic block for plan JSON.

    Instrument parameters are resolved automatically unless ``instrument`` is passed.
    Returns dict with ``exposure_seconds``, ``cadence_seconds``, ``instrument``, etc.
    """
    inst = instrument or resolve_transit_etc_instrument(s, planning_only=planning_only)

    vmag = float(event.get("host_vmag") or 12.0)
    depth_pct = event.get("transit_depth_pct")
    if depth_pct is None or not math.isfinite(float(depth_pct)):
        depth_fraction = 0.01
        depth_warning = "transit_depth_pct 缺失，ETC 假定凌深 1%"
    else:
        depth_fraction = max(float(depth_pct) / 100.0, 1e-5)
        depth_warning = ""

    D_m = inst.aperture_mm / 1000.0
    f_mm = inst.focal_length_mm
    pix_um = inst.pixel_size_um
    scale = _plate_scale_arcsec_per_pixel(f_mm, pix_um)
    seeing_pix = max(s.transit_etc_seeing_arcsec / scale, 1.0)
    effective_n_pix = math.pi * seeing_pix**2

    throughput = s.transit_etc_system_throughput
    if airmass > 1.0:
        # Simple extinction: throughput *= 10^(-0.4 * k * (X-1)), k~0.25 V-band
        throughput *= 10 ** (-0.4 * 0.25 * (airmass - 1.0))

    star_rate = _star_electrons_per_second(
        vmag,
        D_m,
        throughput,
        s.transit_etc_flux_cal_e_per_s_v0_1m,
    )
    sky_rate = _sky_electrons_per_pixel_per_second(
        s.transit_etc_sky_mag_per_arcsec2,
        scale,
        D_m,
        throughput,
        s.transit_etc_flux_cal_e_per_s_v0_1m,
    )
    n_pix = _aperture_pixels(s.transit_etc_aperture_radius_pix)
    read_noise = inst.read_noise_e

    t_min = s.transit_etc_min_exposure_seconds
    t_max = s.transit_etc_max_exposure_seconds
    t_snr = _exposure_for_depth_snr(
        depth_fraction,
        s.transit_etc_target_snr_on_depth,
        star_e_per_s=star_rate,
        sky_e_per_pix_per_s=sky_rate,
        n_pix=n_pix,
        read_noise_e=read_noise,
        t_min=t_min,
        t_max=t_max,
    )
    t_sat = _saturation_limited_exposure(
        star_rate,
        full_well_e=inst.full_well_e,
        peak_fraction=s.transit_etc_saturation_fraction,
        effective_n_pix=effective_n_pix,
    )

    limits: list[str] = []
    warnings: list[str] = list(inst.warnings)
    if depth_warning:
        warnings.append(depth_warning)

    t = t_snr
    if t_sat < t:
        t = t_sat
        limits.append("saturation")
        warnings.append(f"曝光受满阱限制（t_sat≈{t_sat:.1f}s）")

    if t < t_min:
        t = t_min
        limits.append("min_exposure")
    if t > t_max:
        t = t_max
        limits.append("max_exposure")
        warnings.append(f"ETC 建议曝光超过上限，已截断为 {t_max:g}s")

    t = _quantize_exposure(t, s.transit_etc_quantization_seconds)
    overhead = max(0.0, float(s.expose_loop_overhead_seconds))
    cadence = t + overhead

    snr = _photometry_snr(
        t,
        star_e_per_s=star_rate,
        sky_e_per_pix_per_s=sky_rate,
        n_pix=n_pix,
        read_noise_e=read_noise,
    )
    electrons_star = star_rate * t
    snr_on_depth = snr * depth_fraction if depth_fraction > 0 else 0.0

    return {
        "schema_version": ETC_SCHEMA_VERSION,
        "exposure_seconds": t,
        "cadence_seconds": cadence,
        "method": "photon_noise_depth_snr_v1",
        "instrument": instrument_dict_for_etc(inst),
        "inputs": {
            "host_vmag": vmag,
            "transit_depth_pct": depth_pct,
            "transit_depth_fraction": round(depth_fraction, 6),
            "airmass": airmass,
            "aperture_mm": inst.aperture_mm,
            "focal_length_mm": f_mm,
            "pixel_size_um": pix_um,
            "plate_scale_arcsec_per_pixel": round(scale, 4),
            "aperture_radius_pix": s.transit_etc_aperture_radius_pix,
            "photometry_n_pix": round(n_pix, 2),
            "seeing_arcsec": s.transit_etc_seeing_arcsec,
            "effective_core_n_pix": round(effective_n_pix, 2),
            "sky_mag_per_arcsec2": s.transit_etc_sky_mag_per_arcsec2,
            "read_noise_e": read_noise,
            "full_well_e": inst.full_well_e,
            "system_throughput": round(throughput, 4),
            "target_snr_on_depth": s.transit_etc_target_snr_on_depth,
        },
        "computed": {
            "star_electrons_per_second": round(star_rate, 2),
            "sky_electrons_per_pixel_per_second": round(sky_rate, 4),
            "t_from_depth_snr_seconds": round(t_snr, 3),
            "t_saturation_seconds": round(t_sat, 3) if math.isfinite(t_sat) else None,
            "photometry_snr_at_exposure": round(snr, 2),
            "transit_depth_snr_at_exposure": round(snr_on_depth, 2),
            "star_electrons_in_aperture": round(electrons_star, 0),
        },
        "limits_applied": limits,
        "warnings": warnings,
    }
