"""
Layperson natural-language summaries (``nl_simple``) for voice intent results.

Simpler than ``intent_nl.build_intent_nl`` — short sentences, no jargon.
Currently: ``exoplanet_transits``, ``plan_exoplanet_transit``.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

NL_SIMPLE_VERSION = 1

_SIMPLE_HANDLERS: dict[str, Any] = {}


def _lines_to_text(lines: list[str]) -> str:
    return "\n".join(lines)


def _nl_simple_payload(lines: list[str]) -> dict[str, Any]:
    clean = [ln for ln in lines if ln]
    if not clean:
        clean = ["已完成。"]
    return {"version": NL_SIMPLE_VERSION, "text": _lines_to_text(clean), "lines": clean}


def _clock_from_mid_local(mid_local: str) -> str:
    """``2026-06-03 22:30 CST`` → ``22:30``。"""
    m = re.search(r"\d{4}-\d{2}-\d{2}\s+(\d{1,2}:\d{2})", mid_local or "")
    if m:
        return m.group(1)
    return ""


def _sky_position_hint(min_altitude_deg: float | None) -> str:
    if min_altitude_deg is None:
        return ""
    alt = float(min_altitude_deg)
    if alt >= 50:
        return "位置很高，一般比较好拍。"
    if alt >= 30:
        return "位置还可以。"
    return "位置偏低，注意别被房子或树挡住。"


def _visibility_hint(fully_observable: bool | None) -> str:
    if fully_observable is True:
        return "整晚都能拍到。"
    if fully_observable is False:
        return "只有中间一段时间能拍到。"
    return ""


def _exoplanet_transits_simple_lines(result: dict[str, Any]) -> list[str]:
    if result.get("ok") is False:
        msg = result.get("message")
        if msg:
            return [str(msg)]
        return ["暂时查不到今晚的观测安排，请稍后再试。"]

    events = result.get("events") or []
    if not events:
        return [
            "今晚没有查到适合看的系外行星观测。",
            "可以改天再问，或让管理员检查一下网络和设置。",
        ]

    n = len(events)
    lines = [f"今晚查到 {n} 个可以看的观测机会，从最容易的开始："]
    for i, ev in enumerate(events, 1):
        planet = ev.get("planet") or "未知目标"
        when = _clock_from_mid_local(str(ev.get("mid_local") or ""))
        when_s = f"大约 {when} 最明显，" if when else ""
        diff = ev.get("difficulty_label") or "—"
        line = f"第 {i} 个：{planet}，{when_s}难度：{diff}。"
        extras: list[str] = []
        vis = _visibility_hint(ev.get("fully_observable"))
        if vis:
            extras.append(vis)
        sky = _sky_position_hint(ev.get("min_altitude_deg"))
        if sky:
            extras.append(sky)
        if extras:
            line += " " + "".join(extras)
        lines.append(line)
    if n == 1:
        lines.append("想拍这个时，可以说「规划第 1 个」。")
    else:
        lines.append("想拍某一个时，可以说「规划第 1 个」或「规划第 2 个」。")
    return lines


def _format_window_local_short(iso_utc: str, tz: dt.tzinfo) -> str:
    try:
        d = dt.datetime.fromisoformat(str(iso_utc).replace("Z", "+00:00"))
        return d.astimezone(tz).strftime("%H:%M")
    except (ValueError, TypeError):
        return ""


def _plan_exoplanet_transit_simple_lines(result: dict[str, Any]) -> list[str]:
    if result.get("ok") is False:
        msg = result.get("message")
        if msg and "pending" in str(msg).lower():
            return [
                "还没有今晚的观测列表。",
                "请先说「今晚有哪些系外行星观测事件」，再说「规划第 1 个」。",
            ]
        if msg:
            return [str(msg)]
        return ["暂时没法生成观测计划，请稍后再试。"]

    plan = result.get("plan") or {}
    target = plan.get("target") or {}
    window = plan.get("window") or {}
    planet = target.get("planet") or "这个目标"
    diff = target.get("difficulty_label") or ""

    idx = result.get("event_index")
    if idx is not None:
        try:
            lines = [f"已为您安排好今晚列表里的第 {int(idx)} 个观测：{planet}。"]
        except (TypeError, ValueError):
            lines = [f"已为您安排好「{planet}」的今晚自动观测计划。"]
    else:
        lines = [f"已为您安排好「{planet}」的今晚自动观测计划。"]
    if diff:
        lines.append(f"难度：{diff}。")

    from telbot.config import load_settings
    from telbot.planning.window import observer_timezone

    tz = observer_timezone(load_settings())

    start_s = _format_window_local_short(window.get("start_utc", ""), tz)
    end_s = _format_window_local_short(window.get("end_utc", ""), tz)
    if start_s and end_s:
        lines.append(f"预计从今晚 {start_s} 拍到 {end_s}。")
    span = window.get("span_hours")
    if span is not None:
        try:
            h = float(span)
            if h >= 0.5:
                lines.append(f"一共大约 {h:.1f} 小时。")
        except (TypeError, ValueError):
            pass

    inst = plan.get("instrument_profile") or {}
    exp = inst.get("exposure_seconds")
    if exp is not None:
        try:
            lines.append(f"每张图大约拍 {float(exp):.0f} 秒。")
        except (TypeError, ValueError):
            pass

    lines.append("计划已保存在设备里，可以在手机里开始今晚的自动观测。")
    return lines


def _register_handlers() -> None:
    if _SIMPLE_HANDLERS:
        return
    _SIMPLE_HANDLERS["exoplanet_transits"] = _exoplanet_transits_simple_lines
    _SIMPLE_HANDLERS["plan_exoplanet_transit"] = _plan_exoplanet_transit_simple_lines


def build_intent_nl_simple(result: dict[str, Any]) -> dict[str, Any] | None:
    """
    Build beginner-friendly Chinese copy for supported actions.

    Returns None when no simplified template exists (App should use ``nl``).
    """
    _register_handlers()
    action = str(result.get("action") or "")
    fn = _SIMPLE_HANDLERS.get(action)
    if fn is None:
        return None
    return _nl_simple_payload(fn(result))
