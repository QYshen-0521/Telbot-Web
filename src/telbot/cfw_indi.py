"""INDI filter wheel (e.g. QHY CFW3): connect, disconnect, set slot by number or name."""

from __future__ import annotations

import re
from collections.abc import Callable

from telbot.indi import IndiResult, run_getprop, run_setprop

# Default QHY CFW3 slot labels (slot 1–7); override via resolve_filter_slot custom map later if needed.
DEFAULT_FILTER_SLOTS: dict[int, str] = {
    1: "Red",
    2: "Green",
    3: "Blue",
    4: "H_Alpha",
    5: "SII",
    6: "OIII",
    7: "LPR",
}

# User-facing aliases → slot index (lowercase keys).
_FILTER_ALIASES: dict[str, int] = {
    "red": 1,
    "green": 2,
    "blue": 3,
    "h_alpha": 4,
    "h-alpha": 4,
    "ha": 4,
    "halpha": 4,
    "sii": 5,
    "s-ii": 5,
    "oiii": 6,
    "o-iii": 6,
    "o3": 6,
    "lpr": 7,
    # Chinese (voice / text)
    "红": 1,
    "红色": 1,
    "绿": 2,
    "绿色": 2,
    "蓝": 3,
    "蓝色": 3,
    "哈": 4,
    "ha滤镜": 4,
    "氢阿尔法": 4,
    "氢α": 4,
    "hα": 4,
    "sii滤镜": 5,
    "硫": 5,
    "oiii滤镜": 6,
    "氧": 6,
    "宽带": 7,
    "光害": 7,
}


def _normalize_filter_token(token: str) -> str:
    t = token.strip().lower().replace(" ", "_")
    t = re.sub(r"_+", "_", t)
    return t


def _parse_prop_number(stdout: str, element_suffix: str) -> float | None:
    for line in stdout.splitlines():
        line = line.strip()
        if element_suffix in line and "=" in line:
            val = line.rsplit("=", 1)[-1].strip()
            try:
                return float(val)
            except ValueError:
                return None
    return None


def list_filter_slots(*, slots: dict[int, str] | None = None) -> list[dict[str, int | str]]:
    """Return sorted slot list for display / voice list intent."""
    slot_map = slots or DEFAULT_FILTER_SLOTS
    return [{"slot": idx, "name": label} for idx, label in sorted(slot_map.items())]


def resolve_filter_slot(
    slot_or_name: str | int,
    *,
    slots: dict[int, str] | None = None,
) -> int:
    """
    Resolve slot 1–7 from integer or name (e.g. ``red``, ``H_Alpha``, ``4``).

    Names match DEFAULT_FILTER_SLOTS case-insensitively, or entries in ``_FILTER_ALIASES``.
    """
    slot_map = slots or DEFAULT_FILTER_SLOTS
    if isinstance(slot_or_name, int):
        n = slot_or_name
    else:
        raw = str(slot_or_name).strip()
        if not raw:
            raise ValueError("empty filter slot/name")
        if raw.isdigit():
            n = int(raw)
        else:
            key = _normalize_filter_token(raw)
            if key in _FILTER_ALIASES:
                n = _FILTER_ALIASES[key]
            else:
                n = None
                for idx, label in slot_map.items():
                    if _normalize_filter_token(label) == key:
                        n = idx
                        break
                if n is None:
                    known = ", ".join(
                        sorted({*_FILTER_ALIASES.keys(), *(label.lower() for label in slot_map.values())})
                    )
                    raise ValueError(
                        f"unknown filter {raw!r}; use slot 1–{max(slot_map)} or name in: {known}"
                    )
    if n not in slot_map:
        raise ValueError(f"filter slot must be 1–{max(slot_map)}, got {n}")
    return n


def cfw_is_connected(
    device: str,
    host: str,
    port: int,
    *,
    timeout: float,
) -> bool:
    pattern = f"{device}.CONNECTION.*"
    r = run_getprop(host, port, pattern, timeout=timeout)
    if r.returncode != 0:
        return False
    for line in (r.stdout or "").splitlines():
        if ".CONNECTION.CONNECT=" in line:
            return line.rstrip().endswith("=On")
    return False


def cfw_get_slot(
    device: str,
    host: str,
    port: int,
    *,
    timeout: float = 10.0,
) -> tuple[int, int | None, str]:
    pattern = f"{device}.FILTER_SLOT.FILTER_SLOT_VALUE"
    r = run_getprop(host, port, pattern, timeout=timeout)
    if r.returncode != 0:
        return r.returncode, None, r.stderr or r.stdout
    val = _parse_prop_number(r.stdout, "FILTER_SLOT_VALUE")
    if val is None:
        return r.returncode, None, r.stdout
    return r.returncode, int(val), r.stdout


def cfw_connect(
    device: str,
    host: str,
    port: int,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None = None,
) -> IndiResult:
    return run_setprop(
        host,
        port,
        f"{device}.CONNECTION.CONNECT=On",
        dry_run=dry_run,
        on_before_real=on_before_real,
    )


def cfw_disconnect(
    device: str,
    host: str,
    port: int,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None = None,
) -> IndiResult:
    return run_setprop(
        host,
        port,
        f"{device}.CONNECTION.DISCONNECT=On",
        dry_run=dry_run,
        on_before_real=on_before_real,
    )


def cfw_set_slot(
    device: str,
    host: str,
    port: int,
    slot: int,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None = None,
) -> IndiResult:
    return run_setprop(
        host,
        port,
        f"{device}.FILTER_SLOT.FILTER_SLOT_VALUE={slot}",
        dry_run=dry_run,
        on_before_real=on_before_real,
    )
