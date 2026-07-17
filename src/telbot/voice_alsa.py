"""Pick ALSA capture device (plughw:C,D) for arecord; prefer USB mics on Linux/Pi."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class CaptureDevice:
    card: int
    device: int
    card_name: str

    @property
    def plughw(self) -> str:
        return f"plughw:{self.card},{self.device}"


def _parse_arecord_list(text: str) -> list[CaptureDevice]:
    """
    Parse `arecord -l` capture device lines.

    Example line:
      card 1: USB [USB Audio], device 0: USB Audio [USB Audio]
    """
    out: list[CaptureDevice] = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(
            r"^card\s+(\d+):\s*(.+?),\s*device\s+(\d+):",
            line,
            re.IGNORECASE,
        )
        if not m:
            continue
        card = int(m.group(1))
        card_name = m.group(2).strip()
        dev = int(m.group(3))
        out.append(CaptureDevice(card=card, device=dev, card_name=card_name))
    return out


def list_capture_devices() -> list[CaptureDevice]:
    """Return capture devices from `arecord -l`, or [] if unavailable."""
    arecord = shutil.which("arecord")
    if not arecord:
        return []
    try:
        p = subprocess.run(
            [arecord, "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if p.returncode != 0:
        return []
    return _parse_arecord_list(p.stdout or "")


def autodetect_capture_plughw() -> str | None:
    """
    Prefer USB audio capture; else first non-bcm2835 card; else first listed.
    Returns e.g. plughw:1,0 or None if arecord missing / no devices.
    """
    devices = list_capture_devices()
    if not devices:
        return None
    lower = [(d, d.card_name.lower()) for d in devices]
    for d, name in lower:
        if "usb" in name:
            return d.plughw
    for d, name in lower:
        if "bcm2835" not in name and "broadcom" not in name:
            return d.plughw
    return devices[0].plughw


def resolve_listen_arecord_device(
    *,
    cli_override: str | None,
    settings_device: str,
) -> tuple[str, str | None]:
    """
    Pick ALSA device string for arecord.

    Returns (device_string, autodetected_plughw_or_none).
    Order: -D override > non-default .env > autodetect > default.
    """
    o = (cli_override or "").strip()
    if o:
        return o, None
    cfg = (settings_device or "").strip()
    if cfg and cfg != "default":
        return cfg, None
    guess = autodetect_capture_plughw()
    if guess:
        return guess, guess
    return "default", None
