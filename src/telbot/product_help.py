"""First-time user overview of Telbot voice capabilities and supported hardware."""

from __future__ import annotations

from typing import Any

from telbot.usb_devices import list_registered_usb_catalog

# Voice examples grouped for structured payload + NL lines
_CAPABILITY_GROUPS: list[dict[str, Any]] = [
    {
        "title": "望远镜 / 赤道仪",
        "examples": [
            "连接望远镜、解除停车、停车归位",
            "我要看木星、对准 M31",
            "往左一点、往上转一点（微调镜筒）",
            "立刻停止、急停",
        ],
    },
    {
        "title": "相机与校准",
        "examples": [
            "拍照、拍 5 秒",
            "校准、板解（拍照后 ASTAP 解算，可选同步望远镜）",
        ],
    },
    {
        "title": "电调",
        "examples": [
            "查询当前电调位置",
            "把电调向前 / 向后移动 50",
            "帮我自动对焦",
        ],
    },
    {
        "title": "滤镜轮",
        "examples": [
            "查询当前滤镜、有哪些滤镜",
            "切换到红色滤镜、切到 4 号滤镜",
        ],
    },
    {
        "title": "查询与介绍",
        "examples": [
            "介绍一下木星（天体信息，不转动镜筒）",
            "当前有哪些设备连接到 pi",
            "请介绍一下你的功能（本说明）",
            "检查一下设备是否就绪",
        ],
    },
]

def _supported_devices() -> list[dict[str, str]]:
    return list_registered_usb_catalog()


def build_product_help_lines() -> list[str]:
    """Multi-line Chinese guide for new users (CLI / App / TTS)."""
    lines = [
        "你好，我是 Telbot，运行在树莓派上的天文观测语音助手。",
        "你可以用中文说话，我会理解意图并控制已连接的设备；真机操作前请确认镜筒周围安全。",
        "",
        "【目前可以控制的设备类型】",
        "以下硬件需在 USB 上连接并由 INDI 驱动识别（插线后可说「当前有哪些设备连接到 pi」查看）：",
    ]
    for dev in _supported_devices():
        lines.append(f"· {dev['label_zh']}")
    lines.extend(
        [
            "",
            "【语音可以做的事（举例）】",
        ]
    )
    for group in _CAPABILITY_GROUPS:
        lines.append(f"{group['title']}：")
        for ex in group["examples"]:
            lines.append(f"  · {ex}")
    lines.extend(
        [
            "",
            "【第一次使用建议】",
            "· 试说：「请介绍一下你的功能」或「当前有哪些设备连接到 pi」。",
            "· 试说：「介绍一下木星」了解某天体（不会转动望远镜）。",
            "· 要真正转动镜筒、曝光或切换滤镜，请使用 telbot text「…」--apply --execute，"
            "或 telbot listen --apply --execute；也可先只说指令看解析结果。",
            "· 麦克风：telbot listen；需配置 .env 中的观测地经纬度与 INDI 设备名。",
            "",
            "说「帮助」或「请介绍一下你的功能」可随时再听本说明。",
        ]
    )
    return lines


def build_product_help() -> dict[str, Any]:
    """Structured result for action=help (no INDI / USB side effects)."""
    summary_lines = build_product_help_lines()
    return {
        "ok": True,
        "dry_run": True,
        "action": "help",
        "summary_lines": summary_lines,
        "capabilities": _CAPABILITY_GROUPS,
        "supported_devices": _supported_devices(),
    }
