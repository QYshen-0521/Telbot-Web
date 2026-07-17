from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class IndiResult:
    returncode: int
    stdout: str
    stderr: str


def _which_indi() -> tuple[str | None, str | None]:
    getp = shutil.which("indi_getprop")
    setp = shutil.which("indi_setprop")
    return getp, setp


def indi_available() -> bool:
    g, s = _which_indi()
    return g is not None and s is not None


def run_getprop(
    host: str,
    port: int,
    pattern: str = "*.*.*",
    *,
    timeout: float = 10.0,
) -> IndiResult:
    getp, _ = _which_indi()
    if not getp:
        return IndiResult(127, "", "indi_getprop not found (install indi-bin on Linux/Pi)")
    cmd = [getp, "-h", host, "-p", str(port), "-t", str(int(timeout)), pattern]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
    return IndiResult(p.returncode, p.stdout or "", p.stderr or "")


def run_setprop(
    host: str,
    port: int,
    spec: str,
    *,
    dry_run: bool,
    timeout: float = 10.0,
    on_before_real: Callable[[], None] | None = None,
) -> IndiResult:
    """spec: one device.property.element=value or quoted multi-element form."""
    _, setp = _which_indi()
    if dry_run:
        return IndiResult(
            0,
            f"[dry-run] {setp or 'indi_setprop'} -h {host} -p {port} {spec!r}",
            "",
        )
    if not setp:
        return IndiResult(127, "", "indi_setprop not found (install indi-bin on Linux/Pi)")
    if on_before_real is not None:
        on_before_real()
    cmd = [setp, "-h", host, "-p", str(port), "-t", str(int(timeout)), spec]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
    return IndiResult(p.returncode, p.stdout or "", p.stderr or "")


def _getprop_lines_for(host: str, port: int, pattern: str, *, timeout: float) -> tuple[int, str]:
    r = run_getprop(host, port, pattern, timeout=timeout)
    return r.returncode, r.stdout or ""


def telescope_abort_motion_prop_visible(
    host: str,
    port: int,
    device: str,
    *,
    timeout: float,
) -> bool:
    """True if indi_getprop lists TELESCOPE_ABORT_MOTION.ABORT for this device (usually after CONNECT)."""
    rc, out = _getprop_lines_for(host, port, f"{device}.TELESCOPE_ABORT_MOTION.*", timeout=timeout)
    if rc != 0:
        return False
    for line in out.splitlines():
        if ".TELESCOPE_ABORT_MOTION.ABORT" in line and "=" in line:
            return True
    return False


def connection_connect_is_on(host: str, port: int, device: str, *, timeout: float) -> bool | None:
    """None if could not tell."""
    rc, out = _getprop_lines_for(host, port, f"{device}.CONNECTION.CONNECT", timeout=timeout)
    if rc != 0:
        return None
    for line in out.splitlines():
        if ".CONNECTION.CONNECT=" not in line:
            continue
        val = line.split("=", 1)[-1].strip()
        return val == "On"
    return None


def abort_motion_reason_if_unavailable(
    host: str,
    port: int,
    device: str,
    *,
    timeout: float,
) -> str | None:
    """
    If abort cannot be sent (property missing), return a short Chinese reason for stderr.
    Return None if TELESCOPE_ABORT_MOTION.ABORT is visible.
    """
    if telescope_abort_motion_prop_visible(host, port, device, timeout=timeout):
        return None
    lines: list[str] = [
        f"未在 INDI 中发现 {device!r} 的 TELESCOPE_ABORT_MOTION.ABORT。"
        " 多数赤道仪仅在连接后才注册该开关。"
    ]
    con = connection_connect_is_on(host, port, device, timeout=timeout)
    if con is False:
        lines.append("当前 CONNECTION.CONNECT=Off，请先执行：telbot mount connect --execute")
    elif con is True:
        lines.append(
            "已连接但仍无 ABORT 属性：请核对驱动或执行 "
            f"indi_getprop -h {host} -p {port} '{device}.TELESCOPE_ABORT_MOTION.*'"
        )
    return "\n".join(lines)


def telescope_device_names_from_getprop_stdout(stdout: str) -> list[str]:
    """INDI devices that expose EQUATORIAL_EOD_COORD (mount / telescope)."""
    devices: set[str] = set()
    for line in stdout.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key = line.split("=", 1)[0]
        parts = key.split(".", 2)
        if len(parts) < 3:
            continue
        dev = parts[0]
        if "EQUATORIAL_EOD_COORD" in key:
            devices.add(dev)
    return sorted(devices)


def ccd_device_names_from_getprop_stdout(stdout: str) -> list[str]:
    """INDI devices that expose CCD camera properties (CCD_EXPOSURE / CCD_INFO)."""
    devices: set[str] = set()
    for line in stdout.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key = line.split("=", 1)[0]
        if ".CCD_EXPOSURE." in key or ".CCD_INFO." in key:
            devices.add(key.split(".", 1)[0])
    return sorted(devices)


def discover_telescope_devices(host: str, port: int) -> list[str]:
    """All telescope device names (sorted)."""
    r = run_getprop(host, port, "*.*.*")
    if r.returncode != 0:
        return []
    return telescope_device_names_from_getprop_stdout(r.stdout)


def discover_telescope_device(host: str, port: int) -> str | None:
    """First telescope device name (sorted), or None."""
    names = discover_telescope_devices(host, port)
    return names[0] if names else None


def parse_equatorial_eod_stdout(stdout: str) -> tuple[float, float] | None:
    """Parse indi_getprop lines for *.EQUATORIAL_EOD_COORD.RA and .DEC (ignore other *.RA/.DEC)."""
    ra: float | None = None
    dec: float | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, val = line.split("=", 1)
        val = val.split(";")[0].strip()
        if "EQUATORIAL_EOD_COORD" not in key:
            continue
        if key.endswith(".RA"):
            try:
                ra = float(val)
            except ValueError:
                pass
        elif key.endswith(".DEC"):
            try:
                dec = float(val)
            except ValueError:
                pass
    if ra is not None and dec is not None:
        return (ra, dec)
    return None


def read_equatorial_eod(device: str, host: str, port: int, *, timeout: float = 1.0) -> tuple[float, float] | None:
    """Read current RA (h) and Dec (°) from INDI, or None if unavailable."""
    pattern = f"{device}.EQUATORIAL_EOD_COORD.*"
    r = run_getprop(host, port, pattern, timeout=timeout)
    if r.returncode != 0:
        return None
    return parse_equatorial_eod_stdout(r.stdout)


def parse_horizontal_coord_stdout(stdout: str) -> tuple[float, float] | None:
    """Parse ALT/AZ (degrees) from TELESCOPE_HORIZONTAL_COORD or HORIZONTAL_COORD lines."""
    alt: float | None = None
    az: float | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, val = line.split("=", 1)
        val = val.split(";")[0].strip()
        ku = key.upper()
        if "HORIZONTAL" not in ku:
            continue
        if key.endswith(".ALT"):
            try:
                alt = float(val)
            except ValueError:
                pass
        elif key.endswith(".AZ"):
            try:
                az = float(val)
            except ValueError:
                pass
    if alt is not None and az is not None:
        return (alt, az)
    return None


def read_horizontal_coord(
    device: str, host: str, port: int, *, timeout: float = 1.0
) -> tuple[float, float] | None:
    """Read mount ALT/AZ from INDI if the driver exposes horizontal coordinates."""
    for pattern in (
        f"{device}.TELESCOPE_HORIZONTAL_COORD.*",
        f"{device}.HORIZONTAL_COORD.*",
    ):
        r = run_getprop(host, port, pattern, timeout=timeout)
        if r.returncode != 0:
            continue
        parsed = parse_horizontal_coord_stdout(r.stdout)
        if parsed is not None:
            return parsed
    return None


def slew_equatorial_eod(
    device: str,
    host: str,
    port: int,
    ra_hours: float,
    dec_deg: float,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None = None,
) -> tuple[IndiResult, IndiResult]:
    """
    Set EQUATORIAL_EOD_COORD (RA;DEC) then ON_COORD_SET SLEW=On.
    Matches INDI scripting examples (decimal hours / degrees for many mounts).
    """
    # Atomic RA;DEC per indi_setprop docs
    coord = f"{device}.EQUATORIAL_EOD_COORD.RA;DEC={ra_hours};{dec_deg}"
    r1 = run_setprop(host, port, coord, dry_run=dry_run, on_before_real=on_before_real)
    # INDI switch state is typically "On" / "Off"
    slew = f"{device}.ON_COORD_SET.SLEW=On"
    r2 = run_setprop(host, port, slew, dry_run=dry_run)
    return r1, r2


def sync_equatorial_eod(
    device: str,
    host: str,
    port: int,
    ra_hours: float,
    dec_deg: float,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None = None,
) -> tuple[IndiResult, IndiResult]:
    """
    Set EQUATORIAL_EOD_COORD (RA;DEC) then ON_COORD_SET SYNC=On.
    For mounts that expose standard EQUATORIAL_EOD_COORD + ON_COORD_SET (e.g. many LX200-style drivers).
    Element name may differ on some hardware; confirm with: indi_getprop 'Device.ON_COORD_SET.*'
    """
    coord = f"{device}.EQUATORIAL_EOD_COORD.RA;DEC={ra_hours};{dec_deg}"
    r1 = run_setprop(host, port, coord, dry_run=dry_run, on_before_real=on_before_real)
    sync_sw = f"{device}.ON_COORD_SET.SYNC=On"
    r2 = run_setprop(host, port, sync_sw, dry_run=dry_run)
    return r1, r2


def connect_telescope(
    device: str,
    host: str,
    port: int,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None = None,
) -> IndiResult:
    """INDI CONNECTION.CONNECT=On (driver ↔ hardware)."""
    return run_setprop(
        host,
        port,
        f"{device}.CONNECTION.CONNECT=On",
        dry_run=dry_run,
        on_before_real=on_before_real,
    )


def disconnect_telescope(
    device: str,
    host: str,
    port: int,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None = None,
) -> IndiResult:
    """INDI CONNECTION.DISCONNECT=On（与 connect 相反）。"""
    return run_setprop(
        host,
        port,
        f"{device}.CONNECTION.DISCONNECT=On",
        dry_run=dry_run,
        on_before_real=on_before_real,
    )


def unpark_telescope(
    device: str,
    host: str,
    port: int,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None = None,
) -> IndiResult:
    """INDI TELESCOPE_PARK.UNPARK=On."""
    return run_setprop(
        host,
        port,
        f"{device}.TELESCOPE_PARK.UNPARK=On",
        dry_run=dry_run,
        on_before_real=on_before_real,
    )


def park_telescope(
    device: str,
    host: str,
    port: int,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None = None,
) -> IndiResult:
    r = run_setprop(
        host,
        port,
        f"{device}.TELESCOPE_PARK.PARK=On",
        dry_run=dry_run,
        on_before_real=on_before_real,
    )
    return r


def abort_motion(
    device: str,
    host: str,
    port: int,
    *,
    dry_run: bool,
    on_before_real: Callable[[], None] | None = None,
) -> IndiResult:
    if not dry_run:
        reason = abort_motion_reason_if_unavailable(host, port, device, timeout=10.0)
        if reason:
            return IndiResult(1, "", reason)
    r = run_setprop(
        host,
        port,
        f"{device}.TELESCOPE_ABORT_MOTION.ABORT=On",
        dry_run=dry_run,
        on_before_real=on_before_real,
    )
    return r
