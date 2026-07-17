#!/usr/bin/env python3
"""
Standalone auto CONNECT for telbot-select-mount (no ``telbot`` package required).

Copied beside ``telbot_select_mount.py`` in /usr/local/lib/telbot-deploy/.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any


class IndiResult:
    __slots__ = ("returncode", "stdout", "stderr")

    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _run_getprop(host: str, port: int, pattern: str, *, timeout: float) -> IndiResult:
    cmd = shutil.which("indi_getprop")
    if not cmd:
        return IndiResult(127, "", "indi_getprop not found")
    p = subprocess.run(
        [cmd, "-h", host, "-p", str(port), "-t", str(int(timeout)), pattern],
        capture_output=True,
        text=True,
        timeout=timeout + 2,
    )
    return IndiResult(p.returncode, p.stdout or "", p.stderr or "")


def _run_setprop(host: str, port: int, spec: str, *, timeout: float) -> IndiResult:
    cmd = shutil.which("indi_setprop")
    if not cmd:
        return IndiResult(127, "", "indi_setprop not found")
    p = subprocess.run(
        [cmd, "-h", host, "-p", str(port), "-t", str(int(timeout)), spec],
        capture_output=True,
        text=True,
        timeout=timeout + 2,
    )
    return IndiResult(p.returncode, p.stdout or "", p.stderr or "")


def parse_indi_drivers_from_args_line(args_line: str) -> list[str]:
    parts = args_line.strip().split()
    if not parts:
        return []
    if parts[0] == "-p":
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
        return (profile_hint or "").strip() or None
    return None


def collect_pre_connect_setprops(
    manifest: dict,
    jobs: list[tuple[str, str]],
) -> list[str]:
    """INDI setprop specs to run before CONNECTION.CONNECT (e.g. PlaneWave TCP address)."""
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
    _ = optional_drivers_resolved_fn
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


def wait_for_device_visible(
    device: str,
    host: str,
    port: int,
    *,
    timeout_per_try: float = 8.0,
    retries: int = 10,
    pause_s: float = 1.0,
) -> bool:
    pattern = f"{device}.CONNECTION.*"
    for _ in range(max(1, retries)):
        r = _run_getprop(host, port, pattern, timeout=timeout_per_try)
        if r.returncode == 0 and device in (r.stdout or ""):
            return True
        time.sleep(pause_s)
    return False


def connect_indi_device(
    device: str,
    host: str,
    port: int,
    *,
    dry_run: bool,
    setprop_timeout: float = 15.0,
) -> IndiResult:
    spec = f"{device}.CONNECTION.CONNECT=On"
    if dry_run:
        return IndiResult(0, f"[dry-run] indi_setprop … {spec!r}", "")
    return _run_setprop(host, port, spec, timeout=setprop_timeout)


def _is_connected(device: str, host: str, port: int, *, timeout: float) -> bool:
    r = _run_getprop(host, port, f"{device}.CONNECTION.CONNECT", timeout=timeout)
    return r.returncode == 0 and "=On" in (r.stdout or "")


def _apply_pre_connect_setprops(
    specs: list[str],
    host: str,
    port: int,
    *,
    dry_run: bool,
    setprop_timeout: float = 15.0,
) -> list[IndiResult]:
    results: list[IndiResult] = []
    for spec in specs:
        if dry_run:
            results.append(IndiResult(0, f"[dry-run] indi_setprop … {spec!r}", ""))
            continue
        results.append(_run_setprop(host, port, spec, timeout=setprop_timeout))
    return results


def run_auto_connect_jobs(
    jobs: list[tuple[str, str]],
    host: str,
    port: int,
    *,
    dry_run: bool,
    settle_before_s: float = 3.0,
    wait_retries: int = 10,
    pre_connect_setprop: list[str] | None = None,
) -> list[tuple[str, str, IndiResult]]:
    if dry_run or not jobs:
        pre = _apply_pre_connect_setprops(
            pre_connect_setprop or [], host, port, dry_run=True
        )
        _ = pre
        return [(drv, dev, connect_indi_device(dev, host, port, dry_run=True)) for drv, dev in jobs]

    if os.environ.get("TELBOT_SELECT_MOUNT_AUTO_CONNECT_QUICK", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        settle_before_s = min(settle_before_s, 0.5)
    time.sleep(max(0.0, settle_before_s))
    if pre_connect_setprop:
        for spec in pre_connect_setprop:
            r = _run_setprop(host, port, spec, timeout=15.0)
            if r.returncode != 0:
                print(
                    f"Warning: pre-connect setprop {spec!r} failed: {r.stderr or r.stdout}",
                    file=__import__("sys").stderr,
                )
    results: list[tuple[str, str, IndiResult]] = []
    for drv, dev in jobs:
        wait_for_device_visible(dev, host, port, retries=wait_retries)
        r = connect_indi_device(dev, host, port, dry_run=False)
        if r.returncode == 0 and not _is_connected(dev, host, port, timeout=8.0):
            time.sleep(1.5)
            r = connect_indi_device(dev, host, port, dry_run=False)
        results.append((drv, dev, r))
    return results
