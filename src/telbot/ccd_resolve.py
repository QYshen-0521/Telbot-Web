"""Resolve INDI CCD device name from getprop (health / preflight)."""

from __future__ import annotations

import warnings

from telbot.config import Settings, effective_indi_ccd_device_name
from telbot.indi import ccd_device_names_from_getprop_stdout


def _device_in_getprop(blob: str, device: str) -> bool:
    if not device:
        return False
    needle = f"{device}."
    return any(needle in line for line in blob.splitlines())


def resolve_ccd_device_from_getprop_stdout(s: Settings, stdout: str) -> str:
    """
    Pick the CCD device name for this host.

    If ``TELBOT_INDI_CCD_DEVICE`` appears in *stdout*, use it. Otherwise prefer the sole
    CCD candidate from ``CCD_EXPOSURE`` / ``CCD_INFO`` lines (e.g. SBIG when .env still
    has the default ZWO name).
    """
    configured = (s.indi_ccd_device or "").strip()
    fallback = configured or effective_indi_ccd_device_name(s)
    if not stdout:
        return fallback

    if configured and _device_in_getprop(stdout, configured):
        return configured

    candidates = ccd_device_names_from_getprop_stdout(stdout)
    if configured and configured in candidates:
        return configured

    if len(candidates) == 1:
        if configured and configured != candidates[0]:
            warnings.warn(
                f"TELBOT_INDI_CCD_DEVICE={configured!r} 不在 indiserver 中；"
                f"使用检测到的相机 {candidates[0]!r}（可写入 .env）",
                stacklevel=2,
            )
        return candidates[0]

    if len(candidates) > 1 and configured:
        cfg_l = configured.lower()
        for name in candidates:
            if cfg_l in name.lower() or name.lower() in cfg_l:
                return name

    if candidates:
        warnings.warn(
            f"多台 CCD {candidates}；使用 {candidates[0]!r}。"
            " 请设置 TELBOT_INDI_CCD_DEVICE 为 indi_getprop 中的准确名称。",
            stacklevel=2,
        )
        return candidates[0]

    return fallback
