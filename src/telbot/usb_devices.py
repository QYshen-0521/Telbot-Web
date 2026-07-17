"""Scan Pi USB (lsusb) and map known astronomy hardware (see docs/USB_DEVICE_REGISTRY.md)."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from typing import Any

# VID:PID (lowercase) → display fields; keep in sync with docs/USB_DEVICE_REGISTRY.md
_REGISTRY: dict[str, dict[str, str]] = {
    "1fc9:1705": {
        "name": "Losmandy Gemini",
        "label_zh": "赤道仪（Losmandy Gemini）",
        "category": "mount",
    },
    "067b:2303": {
        "name": "Celestron GPS",
        "label_zh": "经纬仪（Celestron GPS / Prolific 串口）",
        "category": "mount",
    },
    "1cbe:0267": {
        "name": "PlaneWave",
        "label_zh": "赤道仪（PlaneWave L350 / PWI4）",
        "category": "mount",
    },
    "0d97:0101": {
        "name": "SBIG CCD",
        "label_zh": "CCD 相机（SBIG）",
        "category": "ccd",
    },
    "10c4:ea60": {
        "name": "QHYCFW3",
        "label_zh": "滤镜轮（QHY CFW3 / CP2102 串口）",
        "category": "cfw",
    },
    "338f:a0f0": {
        "name": "Oasis Focuser",
        "label_zh": "电调（Astroasis Oasis）",
        "category": "focuser",
    },
    "03c3:294f": {
        "name": "ZWO CCD ASI294MC Pro",
        "label_zh": "CCD 相机（ZWO ASI294MC Pro）",
        "category": "ccd",
    },
    "1618:c174": {
        "name": "QHY174 WestBridge",
        "label_zh": "QHY174 引导（WestBridge，固件加载中）",
        "category": "ccd_boot",
    },
    "1618:c175": {
        "name": "QHY CCD QHY174M",
        "label_zh": "CCD 相机（QHY174M / QHYCCD）",
        "category": "ccd",
    },
}


def lsusb_vid_pids() -> set[str]:
    """Return ``vid:pid`` strings from ``lsusb`` (lowercase), or empty if unavailable."""
    try:
        r = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return set()
    if r.returncode != 0:
        return set()
    out: set[str] = set()
    for line in r.stdout.splitlines():
        m = re.search(r"ID ([0-9a-fA-F]{4}):([0-9a-fA-F]{4})", line)
        if m:
            out.add(f"{m.group(1).lower()}:{m.group(2).lower()}")
    return out


def list_registered_usb_catalog() -> list[dict[str, str]]:
    """Known astronomy USB devices from registry (for help / docs)."""
    return [
        {
            "vid_pid": vid,
            "label_zh": info["label_zh"],
            "name": info["name"],
            "category": info["category"],
        }
        for vid, info in sorted(_REGISTRY.items())
    ]


def list_connected_usb_devices(
    *,
    vid_pids: set[str] | None = None,
    lsusb_fn: Callable[[], set[str]] | None = None,
) -> list[dict[str, Any]]:
    """
    Known registry devices currently seen on USB.

    Each item: ``vid_pid``, ``name``, ``label_zh``, ``category``.
    """
    present = vid_pids if vid_pids is not None else (lsusb_fn or lsusb_vid_pids)()
    devices: list[dict[str, Any]] = []
    for vid in sorted(present):
        info = _REGISTRY.get(vid)
        if not info:
            continue
        devices.append(
            {
                "vid_pid": vid,
                "name": info["name"],
                "label_zh": info["label_zh"],
                "category": info["category"],
            }
        )
    return devices


def _empty_usb_slot() -> dict[str, Any]:
    return {
        "connected": False,
        "present": False,
        "configured": True,
        "name": None,
        "label_zh": None,
        "vid_pid": None,
        "category": None,
    }


def _usb_slot_from_device(device: dict[str, Any]) -> dict[str, Any]:
    return {
        "connected": True,
        "present": True,
        "configured": True,
        "name": device.get("name"),
        "label_zh": device.get("label_zh"),
        "vid_pid": device.get("vid_pid"),
        "category": device.get("category"),
    }


def _pick_usb_slot(
    connected: list[dict[str, Any]],
    *,
    categories: tuple[str, ...],
    vid_priority: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Pick one registry device for an App slot (mount / ccd / cfw / focuser)."""
    candidates = [d for d in connected if str(d.get("category") or "") in categories]
    if not candidates:
        return _empty_usb_slot()
    if vid_priority:
        by_vid = {str(d.get("vid_pid") or ""): d for d in candidates}
        for vid in vid_priority:
            if vid in by_vid:
                return _usb_slot_from_device(by_vid[vid])
    return _usb_slot_from_device(candidates[0])


def build_usb_connection_slots(
    connected: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Map ``list_connected_usb_devices()`` to iOS 四槽位（赤道仪 / 主相机 / 滤镜轮 / 电调）。

    与 ``docs/USB_DEVICE_REGISTRY.md`` 中 category 一致；CCD 优先 QHY174M / ZWO，忽略 ``ccd_boot`` 引导芯片。
    """
    if connected is None:
        connected = list_connected_usb_devices()
    ccd_only = [d for d in connected if str(d.get("category") or "") == "ccd"]
    return {
        "mount": _pick_usb_slot(
            connected,
            categories=("mount",),
            vid_priority=("1cbe:0267", "1fc9:1705", "067b:2303"),
        ),
        "main_camera": _pick_usb_slot(
            ccd_only,
            categories=("ccd",),
            vid_priority=("1618:c175", "03c3:294f", "0d97:0101"),
        ),
        "filter_wheel": _pick_usb_slot(connected, categories=("cfw",)),
        "focuser": _pick_usb_slot(connected, categories=("focuser",)),
    }


def format_usb_devices_message(devices: list[dict[str, Any]]) -> str:
    """Short Chinese reply for voice / CLI."""
    if not devices:
        return "当前没有识别到已登记的天文 USB 设备。"
    labels = [str(d.get("label_zh") or d.get("name") or d.get("vid_pid")) for d in devices]
    return "当前已连接：" + "、".join(labels) + "。"
