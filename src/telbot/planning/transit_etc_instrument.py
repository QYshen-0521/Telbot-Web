"""Resolve ETC instrument parameters from catalog, runtime hints, INDI, and platesolve."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from telbot.config import Settings
from telbot.repo_paths import data_dir, telbot_package_dir

_CATALOG_PATH = telbot_package_dir() / "data" / "instrument_etc_catalog.json"
_RUN_TELBOT = Path("/run/telbot")


@dataclass
class ResolvedEtcInstrument:
    aperture_mm: float
    focal_length_mm: float
    pixel_size_um: float
    read_noise_e: float
    full_well_e: float
    sources: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _load_catalog() -> dict[str, Any]:
    path = _catalog_path()
    if not path.is_file():
        return {"defaults": {}, "mount_profiles": {}, "ccd_devices": {}, "ccd_vid_pid": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _catalog_path() -> Path:
    custom = os.environ.get("TELBOT_ETC_CATALOG_PATH", "").strip()
    if custom:
        return Path(custom).expanduser()
    return _CATALOG_PATH


def _read_run_telbot(name: str) -> str:
    p = _RUN_TELBOT / name
    if p.is_file():
        return p.read_text(encoding="utf-8").strip()
    return ""


def _env_override(key: str) -> float | None:
    """Return float only if key is explicitly set in environment (not merely Settings default)."""
    raw = os.environ.get(key)
    if raw is None or not str(raw).strip():
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _match_ccd_device(catalog: dict[str, Any], device: str) -> dict[str, Any] | None:
    devices = catalog.get("ccd_devices") or {}
    d = device.strip()
    if d in devices:
        return devices[d]
    dl = d.lower()
    for name, spec in devices.items():
        if name.lower() in dl or dl in name.lower():
            return spec
    return None


def _ccd_from_usb(catalog: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    try:
        from telbot.usb_devices import lsusb_vid_pids
    except ImportError:
        return None, None
    by_vid = catalog.get("ccd_vid_pid") or {}
    connected = lsusb_vid_pids()
    for vid in sorted(connected):
        if vid in by_vid:
            return by_vid[vid], vid
    return None, None


def _optics_from_mount_profile(catalog: dict[str, Any], profile_id: str) -> dict[str, Any] | None:
    if not profile_id:
        return None
    profiles = catalog.get("mount_profiles") or {}
    spec = profiles.get(profile_id)
    if isinstance(spec, dict):
        return spec
    return None


def _optics_from_mount_profiles_json(profile_id: str) -> dict[str, Any] | None:
    """Optional ``etc_optics`` block in deploy/mount_profiles.json profile entry."""
    if not profile_id:
        return None
    for base in (data_dir().parent / "deploy", telbot_package_dir().parent.parent / "deploy"):
        path = base / "mount_profiles.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for prof in data.get("profiles") or []:
            if prof.get("id") == profile_id:
                optics = prof.get("etc_optics")
                if isinstance(optics, dict):
                    return optics
    return None


def _indi_ccd_info(device: str, host: str, port: int, timeout: float) -> dict[str, float]:
    """Best-effort parse CCD pixel size / gain from indi_getprop (driver-dependent)."""
    try:
        from telbot.indi import indi_available, run_getprop
    except ImportError:
        return {}
    if not indi_available():
        return {}
    pattern = f"{device}.CCD_INFO.*"
    r = run_getprop(host, port, pattern, timeout=timeout)
    if r.returncode != 0:
        return {}
    blob = (r.stdout or "") + (r.stderr or "")
    out: dict[str, float] = {}
    for line in blob.splitlines():
        if "PIXEL_SIZE" in line.upper() or "PIXELSIZ" in line.upper():
            m = re.search(r"=\s*([\d.]+)", line)
            if m:
                val = float(m.group(1))
                # Some drivers report µm, some report mm
                out["pixel_size_um"] = val * 1000.0 if val < 0.05 else val
        if "GAIN" in line.upper() and "ELECTRON" not in line.upper():
            m = re.search(r"=\s*([\d.]+)", line)
            if m:
                g = float(m.group(1))
                if g > 0:
                    out["gain_e_per_adu"] = g
    return out


def _focal_from_platesolve(pixel_size_um: float, s: Settings) -> float | None:
    """Derive focal length from last plate solve pixel scale if available."""
    from telbot.repo_paths import platesolve_last_solve_json

    path = platesolve_last_solve_json()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    scale = data.get("pixel_scale_arcsec_per_pixel")
    if scale is None:
        sol = data.get("solve") or {}
        scale = sol.get("pixel_scale_arcsec_per_pixel")
    if scale is None or float(scale) <= 0 or pixel_size_um <= 0:
        return None
    return 206.265 * pixel_size_um / float(scale)


def _apply_field(
    resolved: ResolvedEtcInstrument,
    key: str,
    value: float | None,
    source: str,
    *,
    required: bool = False,
) -> None:
    if value is None or not (isinstance(value, (int, float)) and value > 0):
        if required:
            resolved.warnings.append(f"未能自动解析 {key}，将使用默认值")
        return
    setattr(resolved, key, float(value))
    resolved.sources[key] = source


def resolve_transit_etc_instrument(
    s: Settings,
    *,
    planning_only: bool = False,
) -> ResolvedEtcInstrument:
    """
    Build instrument model for ETC: catalog + /run/telbot + USB + INDI + platesolve,
    then explicit .env overrides.

    When ``planning_only=True`` (``transit-build`` / voice plan), skip live INDI and
    USB ``lsusb`` probes; use ``.env`` device names + catalog + ``TELBOT_TRANSIT_ETC_*``.
    """
    catalog = _load_catalog()
    defaults = catalog.get("defaults") or {}
    out = ResolvedEtcInstrument(
        aperture_mm=float(defaults.get("aperture_mm", s.transit_etc_aperture_mm)),
        focal_length_mm=float(defaults.get("focal_length_mm", s.transit_etc_focal_length_mm)),
        pixel_size_um=float(defaults.get("pixel_size_um", s.transit_etc_pixel_size_um)),
        read_noise_e=float(defaults.get("read_noise_e", s.transit_etc_read_noise_e)),
        full_well_e=float(defaults.get("full_well_e", s.transit_etc_full_well_e)),
        sources={
            "aperture_mm": "catalog.defaults",
            "focal_length_mm": "catalog.defaults",
            "pixel_size_um": "catalog.defaults",
            "read_noise_e": "catalog.defaults",
            "full_well_e": "catalog.defaults",
        },
    )

    profile_id = _read_run_telbot("mount_profile_id")
    if profile_id:
        mp_spec = _optics_from_mount_profile(catalog, profile_id)
        if mp_spec:
            _apply_field(
                out,
                "aperture_mm",
                mp_spec.get("aperture_mm"),
                f"catalog.mount_profiles:{profile_id}",
            )
            _apply_field(
                out,
                "focal_length_mm",
                mp_spec.get("focal_length_mm"),
                f"catalog.mount_profiles:{profile_id}",
            )
        json_spec = _optics_from_mount_profiles_json(profile_id)
        if json_spec:
            _apply_field(
                out,
                "aperture_mm",
                json_spec.get("aperture_mm"),
                f"mount_profiles.json:etc_optics:{profile_id}",
            )
            _apply_field(
                out,
                "focal_length_mm",
                json_spec.get("focal_length_mm"),
                f"mount_profiles.json:etc_optics:{profile_id}",
            )

    from telbot.config import effective_indi_ccd_device_name

    ccd = effective_indi_ccd_device_name(s)
    if ccd:
        ccd_spec = _match_ccd_device(catalog, ccd)
        if ccd_spec:
            _apply_field(
                out,
                "pixel_size_um",
                ccd_spec.get("pixel_size_um"),
                f"catalog.ccd_devices:{ccd}",
            )
            _apply_field(
                out,
                "read_noise_e",
                ccd_spec.get("read_noise_e"),
                f"catalog.ccd_devices:{ccd}",
            )
            _apply_field(
                out,
                "full_well_e",
                ccd_spec.get("full_well_e"),
                f"catalog.ccd_devices:{ccd}",
            )
        if not planning_only:
            indi_info = _indi_ccd_info(
                ccd,
                s.indi_host,
                s.indi_port,
                max(s.indi_getprop_timeout, 2.0),
            )
            if "pixel_size_um" in indi_info:
                _apply_field(
                    out,
                    "pixel_size_um",
                    indi_info["pixel_size_um"],
                    f"indi:{ccd}.CCD_INFO",
                )

    usb_spec, vid = (None, None)
    if not planning_only:
        usb_spec, vid = _ccd_from_usb(catalog)
    if usb_spec:
        _apply_field(
            out,
            "pixel_size_um",
            usb_spec.get("pixel_size_um"),
            f"catalog.ccd_vid_pid:{vid}",
        )
        _apply_field(
            out,
            "read_noise_e",
            usb_spec.get("read_noise_e"),
            f"catalog.ccd_vid_pid:{vid}",
        )
        _apply_field(
            out,
            "full_well_e",
            usb_spec.get("full_well_e"),
            f"catalog.ccd_vid_pid:{vid}",
        )

    focal_ps = _focal_from_platesolve(out.pixel_size_um, s)
    if focal_ps:
        _apply_field(out, "focal_length_mm", focal_ps, "platesolve:last_solve.json")

    # Site-level OTA (.env → Settings, or explicit env)
    for key, env_key, attr in (
        ("aperture_mm", "TELBOT_OTA_APERTURE_MM", "ota_aperture_mm"),
        ("focal_length_mm", "TELBOT_OTA_FOCAL_LENGTH_MM", "ota_focal_length_mm"),
    ):
        v = _env_override(env_key)
        if v is not None:
            src = f"env:{env_key}"
        elif float(getattr(s, attr, 0) or 0) > 0:
            v = float(getattr(s, attr))
            src = f"settings:{attr}"
        else:
            continue
        _apply_field(out, key, v, src)

    # Per-field ETC overrides (explicit env only)
    override_map = {
        "aperture_mm": "TELBOT_TRANSIT_ETC_APERTURE_MM",
        "focal_length_mm": "TELBOT_TRANSIT_ETC_FOCAL_LENGTH_MM",
        "pixel_size_um": "TELBOT_TRANSIT_ETC_PIXEL_SIZE_UM",
        "read_noise_e": "TELBOT_TRANSIT_ETC_READ_NOISE_E",
        "full_well_e": "TELBOT_TRANSIT_ETC_FULL_WELL_E",
    }
    for attr, env_key in override_map.items():
        v = _env_override(env_key)
        if v is not None and v > 0:
            _apply_field(out, attr, v, f"env:{env_key}")

    if out.sources.get("aperture_mm", "").startswith("catalog.defaults"):
        out.warnings.append(
            "口径/焦距未从选镜 profile 或 OTA 环境变量解析，ETC 使用 catalog.defaults；"
            "建议设置 TELBOT_OTA_APERTURE_MM / TELBOT_OTA_FOCAL_LENGTH_MM"
        )
    return out


def instrument_dict_for_etc(resolved: ResolvedEtcInstrument) -> dict[str, Any]:
    return {
        "aperture_mm": resolved.aperture_mm,
        "focal_length_mm": resolved.focal_length_mm,
        "pixel_size_um": resolved.pixel_size_um,
        "read_noise_e": resolved.read_noise_e,
        "full_well_e": resolved.full_well_e,
        "sources": dict(resolved.sources),
        "warnings": list(resolved.warnings),
    }
