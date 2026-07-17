"""INDI device snapshot for ``GET /health`` (iOS 连接设备页)."""

from __future__ import annotations

import os
from typing import Any

from telbot.ccd_indi import ccd_is_connected
from telbot.ccd_resolve import resolve_ccd_device_from_getprop_stdout
from telbot.config import (
    Settings,
    effective_indi_ccd_device_name,
    effective_indi_cfw_device_name,
    effective_indi_device_name,
    effective_indi_focuser_device_name,
)
from telbot.indi import indi_available, run_getprop
from telbot.mount_resolve import resolve_telescope_device_from_getprop_stdout
from telbot.preflight import _device_in_getprop, _parse_on_off


def _health_getprop_timeout(s: Settings) -> float:
    """Cap INDI probe time for /health so App and serve restart do not hang."""
    base = max(1.0, float(s.indi_getprop_timeout))
    cap = float(os.environ.get("TELBOT_HEALTH_GETPROP_MAX_S", "12"))
    return min(base, max(1.0, cap))


def _connected_from_blob(blob: str, device: str) -> bool:
    return _parse_on_off(blob, device, "CONNECTION", "CONNECT") == "On"


def _device_slot(
    name: str,
    *,
    role: str,
    configured: bool,
    present: bool | None,
    connected: bool,
) -> dict[str, Any]:
    """Shape matches iOS ``extractEquipmentLabel`` / ``mergeDeviceSnapshots``."""
    return {
        "role": role,
        "kind": role,
        "type": role,
        "name": name,
        "device": name,
        "device_name": name,
        "label": name,
        "configured": configured,
        "present": present,
        "connected": connected,
    }


def _ccd_connected(s: Settings, device: str, blob: str) -> bool:
    """CONNECTION from blob when possible; else one targeted getprop (truncated *.*.*)."""
    if blob and _device_in_getprop(blob, device):
        state = _parse_on_off(blob, device, "CONNECTION", "CONNECT")
        if state == "On":
            return True
        if state is not None:
            return False
    if indi_available():
        t = min(3.0, _health_getprop_timeout(s))
        return ccd_is_connected(device, s.indi_host, s.indi_port, timeout=t)
    return False


def _optional_from_blob(
    *,
    device: str,
    blob: str,
    s: Settings | None = None,
    use_ccd_fallback: bool = False,
) -> tuple[bool | None, bool]:
    """Return (present, connected). present=None when not configured."""
    if not device:
        return None, False
    if not blob:
        if use_ccd_fallback and s is not None and indi_available():
            t = min(3.0, _health_getprop_timeout(s))
            if ccd_is_connected(device, s.indi_host, s.indi_port, timeout=t):
                return True, True
        return False, False
    if not _device_in_getprop(blob, device):
        if use_ccd_fallback and s is not None:
            if ccd_is_connected(device, s.indi_host, s.indi_port, timeout=min(3.0, _health_getprop_timeout(s))):
                return True, True
        return False, False
    connected = (
        _ccd_connected(s, device, blob)
        if use_ccd_fallback and s is not None
        else _connected_from_blob(blob, device)
    )
    return True, connected


def _fetch_indi_blob(s: Settings) -> str:
    if not indi_available():
        return ""
    gp_t = _health_getprop_timeout(s)
    r = run_getprop(s.indi_host, s.indi_port, "*.*.*", timeout=gp_t)
    if r.returncode != 0:
        return ""
    return r.stdout or ""


def build_health_devices(s: Settings, *, blob: str | None = None) -> dict[str, Any]:
    """
    Device fields for ``GET /health``.

    Uses **one** ``indi_getprop *.*.*`` (or reuses *blob*) and parses CONNECTION from stdout only —
    no per-device getprop (avoids multi-second /health and serve-restart timeouts).
    """
    if blob is None:
        blob = _fetch_indi_blob(s)

    mount_name = effective_indi_device_name(s)
    if blob:
        try:
            if s.indi_device_auto:
                mount_name = resolve_telescope_device_from_getprop_stdout(s, blob)
            else:
                mount_name = (s.indi_device or "").strip() or mount_name
        except Exception:
            pass

    mount_present: bool | None = False
    mount_connected = False
    if mount_name:
        if blob and _device_in_getprop(blob, mount_name):
            mount_present = True
            mount_connected = _connected_from_blob(blob, mount_name)
        elif not blob:
            mount_present = None

    if blob:
        ccd_name = resolve_ccd_device_from_getprop_stdout(s, blob)
    else:
        ccd_name = (s.indi_ccd_device or "").strip() or effective_indi_ccd_device_name(s)
    ccd_present, ccd_connected = _optional_from_blob(
        device=ccd_name, blob=blob, s=s, use_ccd_fallback=True
    )

    cfw_name = effective_indi_cfw_device_name(s)
    cfw_present, cfw_connected = _optional_from_blob(device=cfw_name, blob=blob)

    foc_name = effective_indi_focuser_device_name(s)
    foc_present, foc_connected = _optional_from_blob(device=foc_name, blob=blob)

    mount_slot = _device_slot(
        mount_name,
        role="mount",
        configured=bool(mount_name),
        present=mount_present,
        connected=mount_connected,
    )
    ccd_slot = _device_slot(
        ccd_name,
        role="ccd",
        configured=bool(ccd_name),
        present=ccd_present,
        connected=ccd_connected,
    )

    devices: list[dict[str, Any]] = [mount_slot, ccd_slot]

    out: dict[str, Any] = {
        "mount": mount_slot,
        "telescope": mount_slot,
        "equatorial_mount": mount_slot,
        "camera": ccd_slot,
        "main_camera": ccd_slot,
        "ccd": ccd_slot,
        "imager": ccd_slot,
        "devices": devices,
        "indi_devices": devices,
        "connected_devices": devices,
    }

    if cfw_name:
        cfw_slot = _device_slot(
            cfw_name,
            role="filter_wheel",
            configured=True,
            present=cfw_present,
            connected=cfw_connected,
        )
        out["filter_wheel"] = cfw_slot
        out["filterwheel"] = cfw_slot
        devices.append(cfw_slot)

    if foc_name:
        foc_slot = _device_slot(
            foc_name,
            role="focuser",
            configured=True,
            present=foc_present,
            connected=foc_connected,
        )
        out["focuser"] = foc_slot
        devices.append(foc_slot)

    return out
