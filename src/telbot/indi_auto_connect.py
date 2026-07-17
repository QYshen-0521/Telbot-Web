"""
After USB profile selection + indiserver restart, CONNECT=On for each loaded driver.

Driver → INDI device name mapping lives in ``mount_profiles.json`` top-level
``auto_connect_by_driver``. Optional ``optional_indi_if`` blocks may set
``auto_connect_device`` per block.
"""

from __future__ import annotations

import re
import time
from typing import Any

from telbot.indi import IndiResult, run_getprop, run_setprop

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7624


def parse_indi_drivers_from_args_line(args_line: str) -> list[str]:
    """Extract ``indi_*`` driver executable names from an indiserver.args line."""
    parts = args_line.strip().split()
    if not parts:
        return []
    if parts[0] == "-p":
        # -p 7624 -v driver1 driver2
        try:
            v_idx = parts.index("-v")
            return [p for p in parts[v_idx + 1 :] if p.startswith("indi_")]
        except ValueError:
            return []
    if parts[0] == "-v":
        return [p for p in parts[1:] if p.startswith("indi_")]
    return [p for p in parts if p.startswith("indi_")]


def _registry_entry(manifest: dict, driver: str) -> dict[str, Any]:
    reg = manifest.get("auto_connect_by_driver") or {}
    return dict(reg.get(driver) or {})


def resolve_device_for_driver(
    driver: str,
    *,
    manifest: dict,
    profile_hint: str,
    optional_devices: dict[str, str],
) -> str | None:
    """
    Return INDI device name to connect, or None to skip.

    ``optional_devices`` maps driver → device from matched ``optional_indi_if`` blocks.
    """
    if driver in optional_devices:
        dev = (optional_devices[driver] or "").strip()
        if dev:
            return dev
    entry = _registry_entry(manifest, driver)
    if entry.get("skip"):
        return None
    if (entry.get("device") or "").strip():
        return entry["device"].strip()
    if entry.get("device_from") == "profile_hint":
        hint = (profile_hint or "").strip()
        return hint or None
    return None


def collect_pre_connect_setprops(
    manifest: dict,
    jobs: list[tuple[str, str]],
) -> list[str]:
    reg = manifest.get("auto_connect_by_driver") or {}
    out: list[str] = []
    seen: set[str] = set()
    for drv, _dev in jobs:
        entry = dict(reg.get(drv) or {})
        for spec in entry.get("pre_connect_setprop") or []:
            s = str(spec).strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    return out


def collect_connect_jobs(
    manifest: dict,
    prof: dict,
    args_line: str,
    vidpids: set[str],
    by_ids: list[str],
    *,
    profile_matches_fn,
    optional_drivers_resolved_fn,
) -> list[tuple[str, str]]:
    """
    List of (driver, indi_device_name) to CONNECTION.CONNECT after restart.

    ``profile_matches_fn`` / ``optional_drivers_resolved_fn`` injected for deploy script reuse.
    """
    drivers = parse_indi_drivers_from_args_line(args_line)
    if not drivers:
        return []
    hint = (prof.get("device_name_hint") or "").strip()
    optional_devices: dict[str, str] = {}
    blocks = prof.get("optional_indi_if")
    if blocks is not None:
        for block in blocks:
            m = block.get("match") or {}
            mode = (block.get("match_mode") or "any").strip().lower()
            syn = {"match": m, "match_mode": mode}
            if profile_matches_fn(syn, vidpids, by_ids):
                for drv in block.get("indi_drivers") or []:
                    ac = (block.get("auto_connect_device") or "").strip()
                    if ac:
                        optional_devices[str(drv)] = ac
    else:
        for drv in prof.get("optional_indi_drivers") or []:
            pass

    jobs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for drv in drivers:
        dev = resolve_device_for_driver(
            drv,
            manifest=manifest,
            profile_hint=hint,
            optional_devices=optional_devices,
        )
        if not dev or dev in seen:
            continue
        seen.add(dev)
        jobs.append((drv, dev))
    return jobs


def connect_indi_device(
    device: str,
    host: str,
    port: int,
    *,
    dry_run: bool,
) -> IndiResult:
    return run_setprop(
        host,
        port,
        f"{device}.CONNECTION.CONNECT=On",
        dry_run=dry_run,
    )


def wait_for_device_prop(
    device: str,
    host: str,
    port: int,
    *,
    timeout_per_try: float = 8.0,
    retries: int = 6,
    pause_s: float = 1.0,
) -> bool:
    pattern = f"{device}.CONNECTION.CONNECT"
    for _ in range(max(1, retries)):
        r = run_getprop(host, port, pattern, timeout=timeout_per_try)
        if r.returncode == 0 and "=On" in (r.stdout or ""):
            return True
        if r.returncode == 0 and device in (r.stdout or ""):
            return True
        time.sleep(pause_s)
    return False


def run_auto_connect_jobs(
    jobs: list[tuple[str, str]],
    host: str,
    port: int,
    *,
    dry_run: bool,
    settle_before_s: float = 2.0,
    wait_retries: int = 6,
    pre_connect_setprop: list[str] | None = None,
    manifest: dict | None = None,
) -> list[tuple[str, str, IndiResult]]:
    """Connect each device; brief settle after restart before first setprop."""
    if manifest is not None and pre_connect_setprop is None:
        pre_connect_setprop = collect_pre_connect_setprops(manifest, jobs)
    if dry_run or not jobs:
        out: list[tuple[str, str, IndiResult]] = []
        for drv, dev in jobs:
            r = connect_indi_device(dev, host, port, dry_run=True)
            out.append((drv, dev, r))
        return out

    time.sleep(max(0.0, settle_before_s))
    for spec in pre_connect_setprop or []:
        r = run_setprop(host, port, spec, dry_run=False)
        if r.returncode != 0:
            pass  # continue; CONNECT may still work if CONFIG_SAVE exists
    results: list[tuple[str, str, IndiResult]] = []
    for drv, dev in jobs:
        wait_for_device_prop(dev, host, port, retries=wait_retries)
        r = connect_indi_device(dev, host, port, dry_run=False)
        results.append((drv, dev, r))
    return results
