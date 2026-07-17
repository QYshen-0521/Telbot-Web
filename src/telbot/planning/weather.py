"""Phase-1 weather: fetch summary for plan window (soft warnings only; no auto veto)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from telbot.config import Settings
from telbot.planning.phase0_config import _norm_weather

# Soft warning thresholds (first version; not tied to Settings yet)
WARN_MEAN_CLOUD_COVER_PCT = 70.0
WARN_MAX_PRECIPITATION_PROB_PCT = 40.0
WARN_MAX_WIND_SPEED_MS = 15.0
WARN_MEAN_RELATIVE_HUMIDITY_PCT = 90.0

OPEN_METEO_TIMEOUT_S = 20.0
SEVEN_TIMER_TIMEOUT_S = 20.0


def _parse_hourly_time(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _http_get_json(url: str, timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "Telbot/0.4 (observing-plan)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def _soft_warnings_from_metrics(
    *,
    mean_cloud_cover_pct: float | None,
    max_precipitation_probability_pct: float | None,
    max_wind_speed_ms: float | None,
    mean_relative_humidity_pct: float | None,
) -> list[str]:
    out: list[str] = []
    if mean_cloud_cover_pct is not None and mean_cloud_cover_pct >= WARN_MEAN_CLOUD_COVER_PCT:
        out.append(f"平均云量较高（约 {mean_cloud_cover_pct:.0f}%），目视/摄影条件可能受限")
    if (
        max_precipitation_probability_pct is not None
        and max_precipitation_probability_pct >= WARN_MAX_PRECIPITATION_PROB_PCT
    ):
        out.append(f"窗口内降水概率峰值较高（约 {max_precipitation_probability_pct:.0f}%）")
    if max_wind_speed_ms is not None and max_wind_speed_ms >= WARN_MAX_WIND_SPEED_MS:
        out.append(f"窗口内风速峰值偏大（约 {max_wind_speed_ms:.1f} m/s），注意视宁度与设备")
    if (
        mean_relative_humidity_pct is not None
        and mean_relative_humidity_pct >= WARN_MEAN_RELATIVE_HUMIDITY_PCT
    ):
        out.append(f"平均相对湿度很高（约 {mean_relative_humidity_pct:.0f}%），注意结露与能见度")
    return out


def _open_meteo_for_window(
    lat: float,
    lon: float,
    start_utc: datetime,
    end_utc: datetime,
    timeout: float,
) -> dict[str, Any]:
    start_utc = start_utc.astimezone(timezone.utc)
    end_utc = end_utc.astimezone(timezone.utc)
    if end_utc <= start_utc:
        return {
            "provider": "open_meteo",
            "error": "invalid_window",
            "message": "时间窗结束须晚于开始",
            "soft_warnings": [],
        }

    start_date = start_utc.date().isoformat()
    end_date = end_utc.date().isoformat()
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "cloud_cover,precipitation_probability,relative_humidity_2m,wind_speed_10m",
        "start_date": start_date,
        "end_date": end_date,
        "timezone": "UTC",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    try:
        data = _http_get_json(url, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as e:
        return {
            "provider": "open_meteo",
            "error": "request_failed",
            "message": str(e),
            "soft_warnings": [f"Open-Meteo 请求失败，已跳过天气摘要：{e}"],
        }

    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return {
            "provider": "open_meteo",
            "error": "no_hourly",
            "message": "响应中无 hourly 数据",
            "soft_warnings": ["Open-Meteo 未返回逐小时数据，已跳过天气摘要"],
        }

    cc = hourly.get("cloud_cover") or []
    pp = hourly.get("precipitation_probability") or []
    rh = hourly.get("relative_humidity_2m") or []
    ws = hourly.get("wind_speed_10m") or []

    idx_in_window: list[int] = []
    for i, t in enumerate(times):
        try:
            ht = _parse_hourly_time(str(t)).astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue
        bucket_end = ht + timedelta(hours=1)
        if ht < end_utc and bucket_end > start_utc:
            idx_in_window.append(i)

    if not idx_in_window:
        return {
            "provider": "open_meteo",
            "error": "no_hours_in_window",
            "message": "所选日期范围内无落入时间窗的小时数据",
            "soft_warnings": ["预报小时与当前时间窗无交集，请检查 --from/--to 或日期"],
        }

    def _take(series: list[Any], indices: list[int]) -> list[float]:
        vals: list[float] = []
        for i in indices:
            if i < len(series) and series[i] is not None:
                try:
                    vals.append(float(series[i]))
                except (TypeError, ValueError):
                    pass
        return vals

    cloud_vals = _take(cc, idx_in_window)
    pp_vals = _take(pp, idx_in_window)
    rh_vals = _take(rh, idx_in_window)
    ws_vals = _take(ws, idx_in_window)

    mean_cloud = sum(cloud_vals) / len(cloud_vals) if cloud_vals else None
    max_pp = max(pp_vals) if pp_vals else None
    mean_rh = sum(rh_vals) / len(rh_vals) if rh_vals else None
    max_wind = max(ws_vals) if ws_vals else None

    fetched_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "sample_hours": len(idx_in_window),
        "mean_cloud_cover_pct": round(mean_cloud, 2) if mean_cloud is not None else None,
        "max_precipitation_probability_pct": round(max_pp, 2) if max_pp is not None else None,
        "mean_relative_humidity_pct": round(mean_rh, 2) if mean_rh is not None else None,
        "max_wind_speed_10m_ms": round(max_wind, 2) if max_wind is not None else None,
    }
    soft = _soft_warnings_from_metrics(
        mean_cloud_cover_pct=mean_cloud,
        max_precipitation_probability_pct=max_pp,
        max_wind_speed_ms=max_wind,
        mean_relative_humidity_pct=mean_rh,
    )
    return {
        "provider": "open_meteo",
        "fetched_at_utc": fetched_at,
        "summary": summary,
        "soft_warnings": soft,
    }


def _seven_timer_summary(lat: float, lon: float, timeout: float) -> dict[str, Any]:
    """7Timer astro product: coarse series (not strictly window-aligned)."""
    params = {"lon": lon, "lat": lat, "product": "astro", "output": "json"}
    url = "https://www.7timer.info/bin/api.pl?" + urllib.parse.urlencode(params)
    try:
        data = _http_get_json(url, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as e:
        return {
            "provider": "seven_timer",
            "error": "request_failed",
            "message": str(e),
            "soft_warnings": [f"7Timer 请求失败：{e}"],
        }

    series = data.get("dataseries") or []
    if not series:
        return {
            "provider": "seven_timer",
            "error": "empty",
            "soft_warnings": ["7Timer 无 dataseries 数据"],
        }

    # cloudcover: 1–9 (网站刻度)，近似映射到百分比用于与 open_meteo 同阈比较
    oktas: list[float] = []
    for row in series:
        c = row.get("cloudcover")
        if c is None:
            continue
        try:
            oktas.append(float(c))
        except (TypeError, ValueError):
            continue
    mean_okta = sum(oktas) / len(oktas) if oktas else None
    approx_cloud_pct = None
    if mean_okta is not None:
        approx_cloud_pct = min(100.0, max(0.0, (mean_okta - 1.0) / 8.0 * 100.0))

    fetched_at = datetime.now(timezone.utc).isoformat()
    soft: list[str] = []
    if approx_cloud_pct is not None and approx_cloud_pct >= WARN_MEAN_CLOUD_COVER_PCT:
        soft.append(f"7Timer 云量指数偏高（近似云量约 {approx_cloud_pct:.0f}%）")

    return {
        "provider": "seven_timer",
        "fetched_at_utc": fetched_at,
        "note": "7Timer 为粗粒度序列，未按夜窗逐小时对齐；仅作参考",
        "summary": {
            "mean_cloudcover_index_1_9": round(mean_okta, 2) if mean_okta is not None else None,
            "approx_mean_cloud_cover_pct": round(approx_cloud_pct, 2) if approx_cloud_pct is not None else None,
            "points": len(series),
        },
        "soft_warnings": soft,
    }


def _qweather_placeholder(s: Settings) -> dict[str, Any]:
    key = (s.plan_weather_api_key or "").strip()
    if not key:
        return {
            "provider": "qweather",
            "skipped": True,
            "reason": "missing_api_key",
            "soft_warnings": ["未设置 TELBOT_PLAN_WEATHER_API_KEY，已跳过 QWeather"],
        }
    return {
        "provider": "qweather",
        "skipped": True,
        "reason": "not_implemented",
        "soft_warnings": [
            "QWeather 逐接口集成尚未实现；请将 TELBOT_PLAN_WEATHER_PROVIDER 设为 open_meteo 或 seven_timer"
        ],
    }


def fetch_weather_for_window(
    s: Settings,
    start_utc: datetime,
    end_utc: datetime,
) -> dict[str, Any]:
    """Return a JSON-serializable weather block for the given UTC window."""
    provider = _norm_weather(s.plan_weather_provider)
    if provider == "none":
        return {
            "provider": "none",
            "skipped": True,
            "soft_warnings": [],
        }
    if provider == "open_meteo":
        return _open_meteo_for_window(
            s.latitude,
            s.longitude,
            start_utc,
            end_utc,
            timeout=OPEN_METEO_TIMEOUT_S,
        )
    if provider == "seven_timer":
        return _seven_timer_summary(s.latitude, s.longitude, timeout=SEVEN_TIMER_TIMEOUT_S)
    if provider == "qweather":
        return _qweather_placeholder(s)
    return {"provider": provider, "error": "unknown_provider", "soft_warnings": []}
