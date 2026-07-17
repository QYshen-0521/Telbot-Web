"""HTTP App 可读写的一小部分 `.env` 参数（见 ``GET/PATCH /config/env``）。"""

from __future__ import annotations

import os
from collections.abc import Callable

from telbot.config import Settings, load_settings
from telbot.env_sync import resolve_dotenv_path, update_dotenv_keys

# App 白名单：不含 API Key / Token 等敏感项。
HTTP_APP_ENV_WHITELIST: frozenset[str] = frozenset(
    {
        # INDI / 设备
        "TELBOT_INDI_HOST",
        "TELBOT_INDI_PORT",
        "TELBOT_INDI_DEVICE",
        "TELBOT_INDI_CCD_DEVICE",
        "TELBOT_INDI_CFW_DEVICE",
        "TELBOT_INDI_FOCUSER_DEVICE",
        # 观测地
        "TELBOT_LATITUDE",
        "TELBOT_LONGITUDE",
        "TELBOT_ELEVATION_M",
        "TELBOT_PLAN_TIMEZONE",
        "TELBOT_MIN_ALTITUDE_DEG",
        # 曝光（非凌星 ETC）
        "TELBOT_CCD_DEFAULT_EXPOSURE_SECONDS",
        "TELBOT_PLAN_DEFAULT_EXPOSURE_SECONDS",
        "TELBOT_EXPOSE_LOOP_OVERHEAD_SECONDS",
        # 凌星 ETC：手动覆盖与 OTA 自动解析
        "TELBOT_TRANSIT_EXPOSURE_SECONDS",
        "TELBOT_OTA_APERTURE_MM",
        "TELBOT_OTA_FOCAL_LENGTH_MM",
        # 凌星 ETC 仪器模型（见 planning/transit_etc.py）
        "TELBOT_TRANSIT_ETC_APERTURE_MM",
        "TELBOT_TRANSIT_ETC_FOCAL_LENGTH_MM",
        "TELBOT_TRANSIT_ETC_PIXEL_SIZE_UM",
        "TELBOT_TRANSIT_ETC_READ_NOISE_E",
        "TELBOT_TRANSIT_ETC_FULL_WELL_E",
        "TELBOT_TRANSIT_ETC_APERTURE_RADIUS_PIX",
        "TELBOT_TRANSIT_ETC_SEEING_ARCSEC",
        "TELBOT_TRANSIT_ETC_SKY_MAG_PER_ARCSEC2",
        "TELBOT_TRANSIT_ETC_SYSTEM_THROUGHPUT",
        "TELBOT_TRANSIT_ETC_TARGET_SNR_ON_DEPTH",
        "TELBOT_TRANSIT_ETC_MIN_EXPOSURE_SECONDS",
        "TELBOT_TRANSIT_ETC_MAX_EXPOSURE_SECONDS",
        # 语音 / LLM / 解算
        "TELBOT_LLM_MODEL",
        "TELBOT_OPENAI_TRANSCRIPTION_MODEL",
        "TELBOT_PLATESOLVE_TIMEOUT_S",
        "TELBOT_INDI_GETPROP_TIMEOUT",
    }
)


def _settings_value_getters() -> dict[str, Callable[[Settings], str]]:
    return {
        "TELBOT_INDI_HOST": lambda s: s.indi_host,
        "TELBOT_INDI_PORT": lambda s: str(s.indi_port),
        "TELBOT_INDI_DEVICE": lambda s: s.indi_device,
        "TELBOT_INDI_CCD_DEVICE": lambda s: s.indi_ccd_device,
        "TELBOT_INDI_CFW_DEVICE": lambda s: s.indi_cfw_device,
        "TELBOT_INDI_FOCUSER_DEVICE": lambda s: s.indi_focuser_device,
        "TELBOT_LATITUDE": lambda s: _format_float(s.latitude),
        "TELBOT_LONGITUDE": lambda s: _format_float(s.longitude),
        "TELBOT_ELEVATION_M": lambda s: _format_float(s.elevation_m),
        "TELBOT_PLAN_TIMEZONE": lambda s: s.plan_timezone,
        "TELBOT_MIN_ALTITUDE_DEG": lambda s: _format_float(s.min_altitude_deg),
        "TELBOT_CCD_DEFAULT_EXPOSURE_SECONDS": lambda s: _format_float(s.ccd_default_exposure_seconds),
        "TELBOT_PLAN_DEFAULT_EXPOSURE_SECONDS": lambda s: _format_float(s.plan_default_exposure_seconds),
        "TELBOT_EXPOSE_LOOP_OVERHEAD_SECONDS": lambda s: _format_float(s.expose_loop_overhead_seconds),
        "TELBOT_TRANSIT_EXPOSURE_SECONDS": lambda s: _format_float(s.transit_exposure_seconds),
        "TELBOT_OTA_APERTURE_MM": lambda s: _format_float(s.ota_aperture_mm),
        "TELBOT_OTA_FOCAL_LENGTH_MM": lambda s: _format_float(s.ota_focal_length_mm),
        "TELBOT_TRANSIT_ETC_APERTURE_MM": lambda s: _format_float(s.transit_etc_aperture_mm),
        "TELBOT_TRANSIT_ETC_FOCAL_LENGTH_MM": lambda s: _format_float(s.transit_etc_focal_length_mm),
        "TELBOT_TRANSIT_ETC_PIXEL_SIZE_UM": lambda s: _format_float(s.transit_etc_pixel_size_um),
        "TELBOT_TRANSIT_ETC_READ_NOISE_E": lambda s: _format_float(s.transit_etc_read_noise_e),
        "TELBOT_TRANSIT_ETC_FULL_WELL_E": lambda s: _format_float(s.transit_etc_full_well_e),
        "TELBOT_TRANSIT_ETC_APERTURE_RADIUS_PIX": lambda s: _format_float(s.transit_etc_aperture_radius_pix),
        "TELBOT_TRANSIT_ETC_SEEING_ARCSEC": lambda s: _format_float(s.transit_etc_seeing_arcsec),
        "TELBOT_TRANSIT_ETC_SKY_MAG_PER_ARCSEC2": lambda s: _format_float(
            s.transit_etc_sky_mag_per_arcsec2
        ),
        "TELBOT_TRANSIT_ETC_SYSTEM_THROUGHPUT": lambda s: _format_float(s.transit_etc_system_throughput),
        "TELBOT_TRANSIT_ETC_TARGET_SNR_ON_DEPTH": lambda s: _format_float(
            s.transit_etc_target_snr_on_depth
        ),
        "TELBOT_TRANSIT_ETC_MIN_EXPOSURE_SECONDS": lambda s: _format_float(
            s.transit_etc_min_exposure_seconds
        ),
        "TELBOT_TRANSIT_ETC_MAX_EXPOSURE_SECONDS": lambda s: _format_float(
            s.transit_etc_max_exposure_seconds
        ),
        "TELBOT_LLM_MODEL": lambda s: s.llm_model,
        "TELBOT_OPENAI_TRANSCRIPTION_MODEL": lambda s: s.openai_transcription_model,
        "TELBOT_PLATESOLVE_TIMEOUT_S": lambda s: _format_float(s.platesolve_timeout_s),
        "TELBOT_INDI_GETPROP_TIMEOUT": lambda s: _format_float(s.indi_getprop_timeout),
    }


def _format_float(v: float) -> str:
    if v == int(v):
        return str(int(v))
    return str(v)


def _validate_keys(keys: list[str]) -> None:
    unknown = sorted(set(keys) - HTTP_APP_ENV_WHITELIST)
    if unknown:
        raise ValueError(f"unknown env keys: {', '.join(unknown)}")


def read_app_env_values(keys: list[str] | None = None) -> dict[str, str]:
    """返回当前进程生效值（合并 .env + os.environ 后由 Settings 解析）。"""
    requested = sorted(HTTP_APP_ENV_WHITELIST if keys is None else keys)
    _validate_keys(requested)
    s = load_settings()
    getters = _settings_value_getters()
    return {k: getters[k](s) for k in requested}


def write_app_env_values(updates: dict[str, str]) -> dict[str, str]:
    """
    原子写入 ``resolve_dotenv_path()`` 指向的 `.env`，并同步 ``os.environ`` 供当前 serve 进程立即生效。
    """
    if not updates:
        raise ValueError("updates empty")
    _validate_keys(list(updates.keys()))
    normalized = {k: v.strip() for k, v in updates.items()}
    path = resolve_dotenv_path()
    update_dotenv_keys(path, normalized, whitelist=HTTP_APP_ENV_WHITELIST)
    for k, v in normalized.items():
        os.environ[k] = v
    return read_app_env_values(list(normalized.keys()))


def app_env_path() -> str:
    return str(resolve_dotenv_path())
