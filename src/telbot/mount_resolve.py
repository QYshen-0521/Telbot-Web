"""Resolve INDI telescope device name from Settings + /run/telbot/indi_device_hint + USB tty."""

from __future__ import annotations

import logging
import re
import warnings
from collections import defaultdict
from pathlib import Path

from telbot.config import Settings
from telbot.indi import run_getprop, telescope_device_names_from_getprop_stdout

_TTY_RE = re.compile(r"/dev/tty(?:ACM|USB|S)[A-Za-z0-9]*")
_DEFAULT_HINT = Path("/run/telbot/indi_device_hint")
_LOG = logging.getLogger(__name__)


def _hint_path(s: Settings) -> Path:
    p = (s.indi_device_hint_path or "").strip()
    return Path(p) if p else _DEFAULT_HINT


def list_usb_tty_paths() -> set[str]:
    """Resolve /dev/serial/by-id/* → canonical tty paths."""
    out: set[str] = set()
    base = Path("/dev/serial/by-id")
    if not base.is_dir():
        return out
    for p in base.iterdir():
        if not p.is_symlink():
            continue
        try:
            target = p.readlink()
            rp = target.resolve() if target.is_absolute() else (base / target).resolve()
            sp = str(rp)
            if sp.startswith("/dev/tty"):
                out.add(sp)
        except OSError:
            continue
    return out


def tty_paths_by_device_from_getprop(stdout: str) -> dict[str, set[str]]:
    """Map INDI device name → /dev/tty* strings mentioned in that device's property values."""
    by_dev: dict[str, set[str]] = defaultdict(set)
    for line in stdout.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, val = line.split("=", 1)
        parts = key.split(".", 2)
        if len(parts) < 3:
            continue
        dev = parts[0]
        val0 = val.split(";")[0].strip()
        for m in _TTY_RE.finditer(val0):
            by_dev[dev].add(m.group(0))
    return dict(by_dev)


def resolve_telescope_device_from_getprop_stdout(s: Settings, stdout: str) -> str:
    """
    Same resolution rules as resolve_telescope_device, but using an existing
    indi_getprop ``*.*.*`` blob (avoids duplicate slow network reads).
    """
    if not s.indi_device_auto:
        return s.indi_device

    candidates = telescope_device_names_from_getprop_stdout(stdout)
    hp = _hint_path(s)
    hint = hp.read_text(encoding="utf-8").strip() if hp.is_file() else ""

    if not candidates:
        if hint:
            # 常见：Celestron 等在未 CONNECT 时尚未挂出 EQUATORIAL_EOD_COORD；用 hint 属预期路径
            _LOG.info(
                "indi_getprop 尚无 EQUATORIAL_EOD_COORD；按 /run/telbot/indi_device_hint 使用 %r",
                hint,
            )
            return hint
        warnings.warn(
            "未发现带 EQUATORIAL_EOD_COORD 的望远镜设备，回退到 TELBOT_INDI_DEVICE",
            stacklevel=2,
        )
        return s.indi_device

    if hint and hint in candidates:
        return hint

    tty_by_dev = tty_paths_by_device_from_getprop(stdout)
    usb_ttys = list_usb_tty_paths()
    for name in candidates:
        if usb_ttys & tty_by_dev.get(name, set()):
            return name

    if len(candidates) == 1:
        return candidates[0]

    warnings.warn(
        f"多台望远镜设备 {candidates}，无法匹配串口；使用 {candidates[0]!r}。"
        " 可关闭 TELBOT_INDI_DEVICE_AUTO 并设置 TELBOT_INDI_DEVICE，或修正 mount_profiles 的 device_name_hint。",
        stacklevel=2,
    )
    return candidates[0]


def resolve_telescope_device(s: Settings) -> str:
    """
    If indi_device_auto is False, return s.indi_device.

    Otherwise: prefer name in /run/telbot/indi_device_hint if it appears in getprop;
    else match EQUATORIAL_EOD_COORD devices to current USB tty paths; else single
    candidate or first sorted with a warning.
    """
    if not s.indi_device_auto:
        return s.indi_device

    # One full ``*.*.*`` fetch; honor TELBOT_INDI_GETPROP_TIMEOUT（不设 10s 下限，避免无谓拖延）
    t = max(1.0, float(s.indi_getprop_timeout))
    r = run_getprop(s.indi_host, s.indi_port, "*.*.*", timeout=t)
    if r.returncode != 0:
        warnings.warn(
            "indi_getprop 失败，TELBOT_INDI_DEVICE_AUTO 回退到 TELBOT_INDI_DEVICE",
            stacklevel=2,
        )
        return s.indi_device

    return resolve_telescope_device_from_getprop_stdout(s, r.stdout)
