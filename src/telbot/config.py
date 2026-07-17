from __future__ import annotations

import os
import warnings
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_dotenv_path(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        out[key] = val
    return out


def telbot_dotenv_layer_paths() -> list[Path]:
    """
    Dotenv files merged for Telbot settings (later file wins for duplicate keys).

    Order: cwd `.env` then `~/Telbot/.env` (deduped). Override with `TELBOT_ENV_FILE`.
    """
    explicit = os.environ.get("TELBOT_ENV_FILE", "").strip()
    if explicit:
        return [Path(explicit).expanduser()]
    out: list[Path] = []
    seen: set[Path] = set()
    for raw in (Path(".env"), Path.home() / "Telbot" / ".env"):
        if not raw.is_file():
            continue
        try:
            r = raw.resolve()
        except OSError:
            continue
        if r in seen:
            continue
        seen.add(r)
        out.append(r)
    return out


def merged_telbot_dotenv() -> dict[str, str]:
    merged: dict[str, str] = {}
    for p in telbot_dotenv_layer_paths():
        merged.update(_parse_dotenv_path(p))
    return merged


def apply_telbot_dotenv_to_environ() -> None:
    """Apply merged dotenv for `TELBOT_*` keys; existing os.environ wins (shell overrides)."""
    for k, v in merged_telbot_dotenv().items():
        if not k.startswith("TELBOT_"):
            continue
        if k not in os.environ:
            os.environ[k] = v


def _read_dotenv_keys() -> dict[str, str]:
    """Parse .env for migration (same line format as pydantic-settings)."""
    return merged_telbot_dotenv()


def _migrate_legacy_observer_env() -> None:
    """
    Prefer TELBOT_LATITUDE / TELBOT_LONGITUDE.
    If only TELBOT_LATITUDE_DEG / TELBOT_LONGITUDE_DEG exist, copy into the new names.
    """
    file_env = _read_dotenv_keys()

    def pick(new: str, legacy: str) -> None:
        if new in file_env:
            return
        if legacy in file_env:
            os.environ.setdefault(new, file_env[legacy])
            return
        if new in os.environ:
            return
        if legacy in os.environ:
            os.environ[new] = os.environ[legacy]

    pick("TELBOT_LATITUDE", "TELBOT_LATITUDE_DEG")
    pick("TELBOT_LONGITUDE", "TELBOT_LONGITUDE_DEG")


class Settings(BaseSettings):
    """Environment-driven INDI connection (override on Pi or dev machine)."""

    # Dotenv is merged in load_settings() (cwd + ~/Telbot/.env); avoid pydantic double-read.
    model_config = SettingsConfigDict(env_prefix="TELBOT_", env_file=None, extra="ignore")

    indi_host: str = "127.0.0.1"
    indi_port: int = 7624
    # Device name as shown by `indi_getprop` (spaces allowed). Example: Losmandy Gemini
    indi_device: str = "Losmandy Gemini"
    # If true, resolve device from /run/telbot/indi_device_hint + indi_getprop + USB tty (see mount_resolve).
    # Multi-mount Pi sites: set true in .env; telbot-select-mount.sh syncs this after USB profile selection.
    indi_device_auto: bool = False
    # Override hint file path (default /run/telbot/indi_device_hint)
    indi_device_hint_path: str = ""
    # INDI CCD device for `telbot camera snap` / VoiceIntent snap (must match indi_getprop exactly).
    indi_ccd_device: str = "ZWO CCD ASI294MC Pro"
    # INDI filter wheel for `telbot filter *` (indi_getprop name, e.g. QHYCFW3)
    indi_cfw_device: str = "QHYCFW3"
    # INDI focuser for `telbot focuser *` (indi_getprop name, e.g. Oasis Focuser)
    indi_focuser_device: str = "Oasis Focuser"
    # Autofocus V-curve (telbot focuser autofocus / voice focuser_autofocus); needs astropy
    autofocus_exposure_seconds: float = 0.0  # 0 = use ccd_default_exposure_seconds
    autofocus_coarse_step: int = 200
    autofocus_fine_step: int = 50
    autofocus_half_range_steps: int = 800
    autofocus_margin_steps: int = 50
    autofocus_settle_seconds: float = 1.0
    autofocus_focuser_timeout_s: float = 60.0
    autofocus_focuser_poll_s: float = 0.5
    # expose_loop (telbot camera expose-loop)
    expose_loop_overhead_seconds: float = 5.0
    # Live stack preview JPEG longest edge (pixels)
    live_stack_preview_max_px: int = 1024
    # Live stack: optional master calibration dirs (from telbot camera cal … sessions)
    live_stack_cal_bias_dir: str = ""
    live_stack_cal_dark_dir: str = ""
    live_stack_cal_flat_dir: str = ""
    # Calibration frames (telbot camera cal …)
    cal_bias_exposure_seconds: float = 0.0
    cal_dark_exposure_seconds: float = 0.0  # 0 = use ccd_default_exposure_seconds for dark
    cal_flat_exposure_seconds: float = 1.0
    cal_default_count: int = 10
    cal_bias_count: int = 0  # 0 = use built-in default (20 for bias)
    cal_dark_count: int = 0
    cal_flat_count: int = 0
    cal_light_count: int = 0
    cal_interval_seconds: float = 0.0  # pause between frames (cooler settle)
    ccd_session_tag: str = ""
    # Default exposure when snap intent omits exposure_seconds
    ccd_default_exposure_seconds: float = 1.0
    # Extra sleep after exposure_seconds on real snap (driver readout; getprop Busy not universal)
    ccd_snap_settle_seconds: float = 3.0
    # Optional: local directory hint for FITS (INDI may still deliver BLOB only to GUI clients)
    ccd_save_dir: str = ""
    # Seconds passed to indi_getprop -t for reads (e.g. nudge: current RA/Dec). Many builds
    # block for roughly this full duration; 15s was unnecessarily slow. Env: TELBOT_INDI_GETPROP_TIMEOUT
    indi_getprop_timeout: float = 1.0
    # Skyfield ephemeris directory (de421.bsp); empty = ~/Telbot (not process CWD)
    skyfield_data_dir: str = ""
    # Observer for Skyfield (degrees, meters). Env: TELBOT_LATITUDE, TELBOT_LONGITUDE
    latitude: float = 0.0
    longitude: float = 0.0
    elevation_m: float = 0.0
    # GOTO / nudge: reject if apparent altitude < this (degrees). Default -0.5 allows
    # refraction + INDI vs Skyfield mismatch near horizon; set 0 for strict "geometric" horizon.
    min_altitude_deg: float = -0.5
    # Relative nudge: RA step (hours), Dec step (degrees)
    nudge_step_ra_hours: float = 1.0 / 60.0
    nudge_step_dec_deg: float = 1.0
    # Semantic intent (sentence-transformers); see embed_intent.py
    semantic_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    semantic_threshold: float = 0.42
    # Cloud STT (OpenAI-compatible transcription API); see telbot listen
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_transcription_model: str = "whisper-1"
    speech_language: str = "zh"
    alsa_arecord_device: str = "default"
    # `telbot listen` 未指定 --seconds 且未使用 --hold-space 时的固定录音时长（秒）
    listen_default_seconds: float = 3.0
    # Cloud LLM intent (OpenAI-compatible chat, e.g. SiliconFlow + Qwen); see llm_intent.py
    intent_use_llm: bool = False
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "Qwen/Qwen2.5-7B-Instruct"
    # Plate solve (ASTAP); pip install -e ".[platesolve]" for astropy
    platesolve_backend: str = "astap"
    platesolve_astap_bin: str = "astap"
    platesolve_timeout_s: float = 180.0
    # ASTAP star database directory (-d); empty = ASTAP default
    platesolve_star_database_dir: str = ""
    # --- Observing plan (phase 0+); see README「观测计划」---
    # Sun apparent altitude (°) below which "auto night" window runs; -6 civil, -12 nautical, -18 astronomical
    plan_night_sun_altitude_threshold_deg: float = -6.0
    # IANA timezone for labeling / future local scheduling (e.g. Asia/Shanghai); empty = system local
    plan_timezone: str = ""
    plan_default_exposure_seconds: float = 60.0
    # Minimum target altitude for planning filter (GOTO safety still uses min_altitude_deg)
    plan_target_min_altitude_deg: float = 30.0
    plan_consider_moon: bool = True
    # When moon illumination fraction (0–100) exceeds this, phase 2 may downrank faint targets
    plan_moon_illumination_max_pct_for_faint: float = 50.0
    # conservative: buffer near meridian / avoid flip overlap; advanced: insert flip windows (later)
    plan_meridian_flip_strategy: str = "conservative"
    plan_meridian_buffer_minutes: float = 10.0
    # open_meteo (no key) | seven_timer | qweather | none — stage 1 implements fetch
    plan_weather_provider: str = "open_meteo"
    plan_weather_api_key: str = ""
    plan_weather_query_interval_minutes: float = 30.0
    # Phase 2: catalog + schedule (see README)
    # messier | ngc_bright | messier_ngc — requires OpenNGC CSV (telbot catalog download-openngc)
    plan_catalog_sources: str = "messier"
    plan_ngc_max_vmag: float = 10.0
    plan_candidate_limit: int = 120
    plan_goto_buffer_seconds: float = 120.0
    # Comma-separated azimuth ranges (°), clockwise from North, e.g. "0-35,145-215"; empty = no azimuth filter
    plan_forbidden_azimuth_deg_ranges: str = ""
    plan_phase2_time_step_minutes: float = 15.0
    # Targets with V-Mag above this (or unknown mag) count as "faint" for moon downrank
    plan_faint_vmag_threshold: float = 10.0
    # Phase 5: telbot plan monitor — interval & park thresholds (Open-Meteo summary fields)
    plan_monitor_interval_minutes: float = 30.0
    plan_monitor_forecast_horizon_hours: float = 3.0
    plan_monitor_park_mean_cloud_pct: float = 85.0
    plan_monitor_park_precip_prob_pct: float = 55.0
    plan_monitor_park_wind_ms: float = 18.0
    # Exoplanet transit events (telbot plan transits / voice exoplanet_transits); needs pip install -e ".[exoplanets]"
    exoplanet_max_host_vmag: float = 12.0
    exoplanet_min_altitude_deg: float = 30.0
    exoplanet_catalog_scan_limit: int = 150
    exoplanet_max_results: int = 15
    exoplanet_consider_moon: bool = True
    # Exoplanet transit observing plan (telbot plan transit-build / transit-run)
    transit_baseline_h: float = 1.0
    transit_baseline_k: float = 1.5
    transit_default_filter: str = "Clear"
    transit_exposure_seconds: float = 0.0  # >0 = skip ETC, force this exposure (seconds)
    # OTA optics for ETC auto-resolve (0 = try catalog / mount profile / platesolve)
    ota_aperture_mm: float = 0.0
    ota_focal_length_mm: float = 0.0
    transit_include_autofocus: bool = True
    transit_include_platesolve: bool = False
    transit_include_ingress_precheck: bool = True
    transit_ingress_precheck_min: float = 10.0
    transit_ingress_precheck_exposure_seconds: float = 0.0
    transit_ingress_precheck_max_offset_arcmin: float = 8.0
    transit_ingress_precheck_fail_policy: str = "continue"
    transit_pending_ttl_hours: float = 12.0
    transit_setup_connect_min: float = 45.0
    transit_setup_unpark_min: float = 40.0
    transit_setup_goto_min: float = 35.0
    transit_setup_cfw_min: float = 30.0
    transit_setup_autofocus_min: float = 25.0
    transit_setup_platesolve_min: float = 20.0
    # Transit ETC (planning/transit_etc.py) — default science exposure when building plan
    transit_etc_aperture_mm: float = 200.0
    transit_etc_focal_length_mm: float = 1000.0
    transit_etc_pixel_size_um: float = 5.5
    transit_etc_read_noise_e: float = 3.0
    transit_etc_full_well_e: float = 60000.0
    transit_etc_aperture_radius_pix: float = 12.0
    transit_etc_seeing_arcsec: float = 2.0
    transit_etc_sky_mag_per_arcsec2: float = 21.0
    transit_etc_system_throughput: float = 0.35
    transit_etc_flux_cal_e_per_s_v0_1m: float = 6.0e9
    transit_etc_target_snr_on_depth: float = 5.0
    transit_etc_saturation_fraction: float = 0.8
    transit_etc_min_exposure_seconds: float = 1.0
    transit_etc_max_exposure_seconds: float = 600.0
    transit_etc_quantization_seconds: float = 0.5


def _settings_field_default(field: str) -> str:
    default = Settings.model_fields[field].default
    return "" if default is None else str(default)


def effective_indi_device_name(s: Settings) -> str:
    """Mount device for planning/CLI; empty .env → built-in default (no INDI required)."""
    v = (s.indi_device or "").strip()
    return v if v else _settings_field_default("indi_device")


def effective_indi_ccd_device_name(s: Settings) -> str:
    """CCD device for planning/CLI; empty .env → built-in default."""
    v = (s.indi_ccd_device or "").strip()
    return v if v else _settings_field_default("indi_ccd_device")


def effective_indi_cfw_device_name(s: Settings) -> str:
    """Filter wheel name; empty string in .env means «no CFW» (no fallback)."""
    return (s.indi_cfw_device or "").strip()


def effective_indi_focuser_device_name(s: Settings) -> str:
    """Focuser name; empty string in .env means «no focuser» (no fallback)."""
    return (s.indi_focuser_device or "").strip()


def _warn_if_observer_incomplete(s: Settings) -> None:
    """Latitude 0 + nonzero longitude (or the reverse) makes horizon checks wrong (e.g. Polaris near 0° alt)."""
    if abs(s.latitude) < 1e-9 and abs(s.longitude) > 1e-9:
        warnings.warn(
            "TELBOT_LATITUDE 为 0 但 TELBOT_LONGITUDE 已设置：地平计算会按「赤道上的观测者」处理，"
            "北极星等目标会被误判接近/低于地平。请在 .env 中设置 TELBOT_LATITUDE（例如上海约 31.2）。",
            stacklevel=2,
        )
    elif abs(s.longitude) < 1e-9 and abs(s.latitude) > 1e-9:
        warnings.warn(
            "TELBOT_LONGITUDE 为 0 但 TELBOT_LATITUDE 已设置：地平经度错误。请检查 .env 中的 TELBOT_LONGITUDE。",
            stacklevel=2,
        )


def load_settings() -> Settings:
    apply_telbot_dotenv_to_environ()
    _migrate_legacy_observer_env()
    s = Settings()
    _warn_if_observer_incomplete(s)
    return s
