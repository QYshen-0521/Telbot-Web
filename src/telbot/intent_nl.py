"""
Rule-based natural-language JSON from ``execute_voice_intent`` / ``describe`` results.

App-facing payload contains only human-readable fields (see docs/INTENT_NATURAL_LANGUAGE.md).
"""

from __future__ import annotations

from typing import Any

from telbot.usb_devices import format_usb_devices_message

NL_VERSION = 1

_NUDGE_ZH: dict[str, str] = {
    "up": "上（赤纬增加）",
    "down": "下（赤纬减少）",
    "left": "左（赤经减少）",
    "right": "右（赤经增加）",
}
_FOCUSER_DIR_ZH: dict[str, str] = {"in": "向内", "out": "向外"}


def _lines_to_text(lines: list[str]) -> str:
    return "\n".join(lines)


def _nl_payload(lines: list[str]) -> dict[str, Any]:
    clean = [ln for ln in lines if ln]
    if not clean:
        clean = ["操作已完成。"]
    return {"version": NL_VERSION, "text": _lines_to_text(clean), "lines": clean}


def _status_word(ok: bool, dry_run: bool) -> str:
    if dry_run:
        return "（模拟，未真机执行）"
    return "成功" if ok else "失败"


def _mount_simple(action: str, result: dict[str, Any]) -> list[str]:
    dev = result.get("device") or "望远镜"
    verb = {
        "connect": "连接",
        "unpark": "解除停车",
        "park": "停车归位",
        "abort": "中止运动",
    }.get(action, action)
    ok = bool(result.get("ok"))
    dry = bool(result.get("dry_run"))
    if dry:
        return [f"将{verb}设备「{dev}」。（模拟，未真机执行）"]
    return [f"{verb}设备「{dev}」{_status_word(ok, dry)}。"]


def _goto_lines(result: dict[str, Any]) -> list[str]:
    dry = bool(result.get("dry_run"))
    ok = bool(result.get("ok"))
    resolved = result.get("resolved") or {}
    label = resolved.get("label") or result.get("target") or "目标"
    ra = resolved.get("ra_hours")
    dec = resolved.get("dec_deg")
    alt = resolved.get("altitude_deg")
    parts = [f"指向「{label}」"]
    if ra is not None and dec is not None:
        parts.append(f"赤经 {ra:.4f} 时、赤纬 {dec:.2f}°")
    if alt is not None:
        parts.append(f"当前高度约 {alt:.1f}°")
    head = "，".join(parts) + "。"
    if dry:
        return [head, "（模拟，未发送 GOTO 命令）"]
    return [head + f" GOTO {_status_word(ok, dry)}。"]


def _nudge_lines(result: dict[str, Any]) -> list[str]:
    resolved = result.get("resolved") or {}
    direction = resolved.get("direction") or ""
    dir_zh = _NUDGE_ZH.get(str(direction), direction)
    dry = bool(result.get("dry_run"))
    ok = bool(result.get("ok"))
    if dry:
        return [f"将向{dir_zh}微移镜筒。（模拟，未真机执行）"]
    return [f"已向{dir_zh}微移镜筒，{_status_word(ok, dry)}。"]


def _snap_lines(result: dict[str, Any]) -> list[str]:
    sec = result.get("exposure_seconds")
    dry = bool(result.get("dry_run"))
    ok = bool(result.get("ok"))
    ccd = result.get("device") or "CCD"
    if dry:
        return [f"将对「{ccd}」曝光 {sec} 秒。（模拟，未真机执行）"]
    line = f"「{ccd}」曝光 {sec} 秒，{_status_word(ok, dry)}。"
    hint = result.get("save_dir_hint")
    if ok and hint:
        line += f" 图像保存目录：{hint}。"
    return [line]


def _platesolve_lines(result: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    dry = bool(result.get("dry_run"))
    ok = bool(result.get("ok"))
    if msg := result.get("message"):
        lines.append(str(msg))
    snap = result.get("snap")
    if isinstance(snap, dict):
        sec = snap.get("exposure_seconds")
        if dry:
            lines.append(f"将先曝光 {sec} 秒再板解。（模拟）")
        elif not snap.get("ok"):
            lines.append("CCD 曝光步骤失败。")
    solve = result.get("solve")
    if isinstance(solve, dict):
        if solve.get("skipped") == "dry_run":
            lines.append(str(solve.get("message") or "干跑不执行 ASTAP 解算。"))
        elif solve.get("message"):
            lines.append(f"解算：{solve['message']}")
    elif result.get("message") is None and not dry:
        if ok:
            lines.append("板解完成。")
        else:
            lines.append("板解失败。")
    if ra := result.get("jnow_ra_hours"):
        dec = result.get("jnow_dec_deg")
        if dec is not None:
            lines.append(f"解算中心（JNow）：赤经 {float(ra):.4f} 时、赤纬 {float(dec):.2f}°。")
    align = result.get("align")
    if isinstance(align, dict):
        mode = align.get("mode") or ""
        mode_zh = "同步" if mode == "sync" else "指向" if mode == "slew" else mode
        if align.get("skipped") == "dry_run":
            lines.append(str(align.get("message") or f"解算后{mode_zh}对准未执行（干跑）。"))
        elif align.get("error"):
            lines.append(f"对准（{mode_zh}）失败：{align['error']}")
        elif align.get("ok"):
            lines.append(f"对准（{mode_zh}）成功。")
        else:
            lines.append(f"对准（{mode_zh}）未完成。")
    if not lines:
        if dry:
            lines.append("将执行拍照与板解。（模拟，未真机执行）")
        else:
            lines.append(f"板解流程{_status_word(ok, dry)}。")
    return lines


def _focuser_position_lines(result: dict[str, Any]) -> list[str]:
    if result.get("message"):
        return [str(result["message"]) + ("（模拟）" if result.get("dry_run") else "")]
    pos = result.get("position")
    mx = result.get("max")
    foc = result.get("device") or "电调"
    if pos is None:
        return [f"无法读取「{foc}」位置。"]
    line = f"「{foc}」当前位置：{pos}"
    if mx is not None:
        line += f"，最大行程 {mx}"
    line += "。"
    return [line]


def _focuser_rel_lines(result: dict[str, Any]) -> list[str]:
    direction = result.get("focuser_direction") or ""
    steps = result.get("focuser_steps")
    dir_zh = _FOCUSER_DIR_ZH.get(str(direction), direction)
    foc = result.get("device") or "电调"
    dry = bool(result.get("dry_run"))
    ok = bool(result.get("ok"))
    if dry:
        return [f"将驱动「{foc}」{dir_zh}移动 {steps} 步。（模拟，未真机执行）"]
    line = f"「{foc}」已{dir_zh}移动 {steps} 步，{_status_word(ok, dry)}。"
    if pos_after := result.get("position_after"):
        line += f" 当前位置：{pos_after}。"
    return [line]


def _focuser_autofocus_lines(result: dict[str, Any]) -> list[str]:
    if result.get("message"):
        msg = str(result["message"])
        if result.get("dry_run"):
            msg += "（模拟）"
        return [msg]
    if not result.get("ok"):
        return ["自动对焦失败。"]
    best = result.get("best_position")
    hfr = result.get("best_hfr")
    start = result.get("start_position")
    if best is not None and hfr is not None:
        return [f"自动对焦完成：位置 {start} → {best}，HFR≈{hfr:.2f}px。"]
    return ["自动对焦完成。"]


def _cfw_current_lines(result: dict[str, Any]) -> list[str]:
    if result.get("message"):
        return [str(result["message"]) + ("（模拟）" if result.get("dry_run") else "")]
    slot = result.get("slot")
    name = result.get("name") or ""
    cfw = result.get("device") or "滤镜轮"
    return [f"「{cfw}」当前滤镜：槽位 {slot}（{name}）。"]


def _cfw_list_lines(result: dict[str, Any]) -> list[str]:
    filters = result.get("filters") or []
    if not filters:
        return ["暂无可用滤镜列表。"]
    parts = [f"{f.get('slot')}号 {f.get('name')}" for f in filters if f.get("slot") is not None]
    return [f"可用滤镜共 {len(parts)} 个：" + "、".join(parts) + "。"]


def _cfw_goto_lines(result: dict[str, Any]) -> list[str]:
    cfw = result.get("device") or "滤镜轮"
    slot = result.get("slot")
    name = result.get("name") or ""
    target = result.get("target") or ""
    dry = bool(result.get("dry_run"))
    ok = bool(result.get("ok"))
    if dry:
        return [f"将把「{cfw}」切换到槽位 {slot}（{name}，目标 {target!s}）。（模拟，未真机执行）"]
    line = f"「{cfw}」已切换到槽位 {slot}（{name}），{_status_word(ok, dry)}。"
    if slot_after := result.get("slot_after"):
        line += f" 当前槽位：{slot_after}。"
    return [line]


def _usb_devices_lines(result: dict[str, Any]) -> list[str]:
    if result.get("message"):
        return [str(result["message"])]
    devices = result.get("devices") or []
    return [format_usb_devices_message(devices)]


def _help_lines(result: dict[str, Any]) -> list[str]:
    lines = result.get("summary_lines")
    if isinstance(lines, list) and lines:
        return [str(x) for x in lines]
    return ["Telbot 是树莓派上的天文观测语音助手，可以说「请介绍一下你的功能」了解详情。"]


def _preflight_lines(result: dict[str, Any]) -> list[str]:
    msg = result.get("message")
    if msg:
        return str(msg).splitlines()
    ready = result.get("ready")
    if ready:
        return ["设备就绪诊断通过。"]
    return ["设备就绪诊断未通过，请查看 checks 详情。"]


def _exoplanet_transits_lines(result: dict[str, Any]) -> list[str]:
    if result.get("message"):
        return str(result["message"]).splitlines()
    events = result.get("events") or []
    if not events:
        return ["今晚没有符合条件的系外行星凌星事件。"]
    return [str(result.get("message") or f"共 {len(events)} 个凌星事件。")]


def _plan_exoplanet_transit_lines(result: dict[str, Any]) -> list[str]:
    summary = result.get("summary") or result.get("message")
    if summary:
        return str(summary).splitlines()
    path = result.get("saved_path")
    if path:
        return [f"已生成凌星计划：{path}"]
    return ["凌星观测计划已生成。"]


def _describe_lines(result: dict[str, Any]) -> list[str]:
    intro = result.get("intro") or {}
    lines = intro.get("summary_lines")
    if isinstance(lines, list) and lines:
        return [str(x) for x in lines]
    label = intro.get("label") or intro.get("query") or "天体"
    return [f"已查询天体「{label}」的信息。"]


def attach_intent_nl(result: dict[str, Any]) -> dict[str, Any]:
    """Copy *result* and add sibling ``nl`` (and ``nl_simple`` when available) for App / TTS."""
    merged = dict(result)
    merged["nl"] = build_intent_nl(result)
    from telbot.intent_nl_simple import build_intent_nl_simple

    nl_simple = build_intent_nl_simple(result)
    if nl_simple is not None:
        merged["nl_simple"] = nl_simple
    return merged


def build_intent_nl(result: dict[str, Any]) -> dict[str, Any]:
    """
    Build App-facing natural-language JSON from a raw execution/describe result dict.

    Returns ``{"version": 1, "text": "…", "lines": ["…", …]}`` (Chinese).
    """
    action = str(result.get("action") or "")
    handlers: dict[str, Any] = {
        "help": _help_lines,
        "preflight": _preflight_lines,
        "exoplanet_transits": _exoplanet_transits_lines,
        "plan_exoplanet_transit": _plan_exoplanet_transit_lines,
        "describe": _describe_lines,
        "usb_devices": _usb_devices_lines,
        "connect": lambda r: _mount_simple("connect", r),
        "unpark": lambda r: _mount_simple("unpark", r),
        "park": lambda r: _mount_simple("park", r),
        "abort": lambda r: _mount_simple("abort", r),
        "goto": _goto_lines,
        "nudge": _nudge_lines,
        "snap": _snap_lines,
        "platesolve": _platesolve_lines,
        "focuser_position": _focuser_position_lines,
        "focuser_rel": _focuser_rel_lines,
        "focuser_autofocus": _focuser_autofocus_lines,
        "cfw_current": _cfw_current_lines,
        "cfw_list": _cfw_list_lines,
        "cfw_goto": _cfw_goto_lines,
    }
    fn = handlers.get(action)
    if fn is not None:
        return _nl_payload(fn(result))
    ok = result.get("ok")
    dry = result.get("dry_run")
    if ok is True:
        return _nl_payload(["操作成功。" + ("（模拟）" if dry else "")])
    if ok is False:
        return _nl_payload(["操作失败。" + (str(result.get("message")) if result.get("message") else "")])
    return _nl_payload([str(result.get("message") or "操作已完成。")])
