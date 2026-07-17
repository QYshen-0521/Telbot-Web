"""Device readiness checks before real observing (preflight)."""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from telbot.ccd_indi import ccd_is_connected
from telbot.ccd_paths import ccd_captures_base_dir, prepare_ccd_save_directory
from telbot.cfw_indi import cfw_is_connected
from telbot.config import Settings
from telbot.env_sync import resolve_dotenv_path
from telbot.focuser_indi import focuser_get_absolute_position, focuser_is_connected
from telbot.indi import indi_available, run_getprop
from telbot.indi_service import indi_status_lines
from telbot.ccd_resolve import resolve_ccd_device_from_getprop_stdout
from telbot.mount_resolve import resolve_telescope_device

PreflightStatus = Literal["ok", "warn", "fail", "skip"]


@dataclass(frozen=True)
class PreflightCheck:
    id: str
    category: str
    status: PreflightStatus
    title: str
    detail: str


def _add(checks: list[PreflightCheck], **kwargs: str) -> None:
    checks.append(PreflightCheck(**kwargs))  # type: ignore[arg-type]


def _device_in_getprop(blob: str, device: str) -> bool:
    if not device:
        return False
    needle = f"{device}."
    return any(needle in line for line in blob.splitlines())


def _parse_on_off(blob: str, device: str, prop: str, element: str) -> str | None:
    prefix = f"{device}.{prop}.{element}="
    for line in blob.splitlines():
        if prefix in line:
            return line.split("=", 1)[-1].strip().split(";")[0]
    return None


def _format_checks_message(checks: list[PreflightCheck], *, ready: bool) -> str:
    icons = {"ok": "✓", "warn": "!", "fail": "✗", "skip": "−"}
    lines = ["设备就绪诊断：" + ("通过" if ready else "未通过")]
    for c in checks:
        if c.status == "skip":
            continue
        lines.append(f"  {icons[c.status]} [{c.category}] {c.title} — {c.detail}")
    return "\n".join(lines)


def run_preflight(s: Settings, *, include_indi_service: bool = True) -> dict[str, Any]:
    """
    Run preflight checks. ``ready`` is True when no check has status ``fail``.

    Uses one indi_getprop ``*.*.*`` when INDI is reachable (same as mount discover).
    """
    checks: list[PreflightCheck] = []
    gp_t = max(1.0, float(s.indi_getprop_timeout))
    blob = ""

    if not indi_available():
        _add(
            checks,
            id="indi_tools",
            category="工具",
            status="fail",
            title="indi_getprop / indi_setprop",
            detail="未找到 INDI 命令行工具（安装 indi-bin）",
        )
    else:
        _add(
            checks,
            id="indi_tools",
            category="工具",
            status="ok",
            title="indi_getprop / indi_setprop",
            detail="已安装",
        )

    env_path = resolve_dotenv_path()
    if env_path.is_file():
        if os.access(env_path, os.R_OK):
            _add(
                checks,
                id="dotenv",
                category="配置",
                status="ok",
                title=".env 可读",
                detail=str(env_path),
            )
        else:
            _add(
                checks,
                id="dotenv",
                category="配置",
                status="fail",
                title=".env 权限",
                detail=f"无法读取 {env_path}（Permission denied；见 docs/MOUNT_AUTO.md）",
            )
    else:
        _add(
            checks,
            id="dotenv",
            category="配置",
            status="warn",
            title=".env",
            detail=f"未找到 {env_path}，将仅用环境变量/默认值",
        )

    lat_ok = abs(s.latitude) > 1e-9
    lon_ok = abs(s.longitude) > 1e-9
    if lat_ok and lon_ok:
        _add(
            checks,
            id="observer",
            category="观测站",
            status="ok",
            title="经纬度",
            detail=f"lat={s.latitude:.5f}° lon={s.longitude:.5f}°",
        )
    elif lat_ok and not lon_ok:
        _add(
            checks,
            id="observer",
            category="观测站",
            status="fail",
            title="经度缺失",
            detail="TELBOT_LATITUDE 已设但 TELBOT_LONGITUDE 为 0；地平/GOTO 会错误",
        )
    elif lon_ok and not lat_ok:
        _add(
            checks,
            id="observer",
            category="观测站",
            status="fail",
            title="纬度缺失",
            detail="TELBOT_LONGITUDE 已设但 TELBOT_LATITUDE 为 0",
        )
    else:
        _add(
            checks,
            id="observer",
            category="观测站",
            status="warn",
            title="经纬度未配置",
            detail="TELBOT_LATITUDE / TELBOT_LONGITUDE 均为 0；请填写台址",
        )

    cap_base = ccd_captures_base_dir(s.ccd_save_dir)
    try:
        prepare_ccd_save_directory(s.ccd_save_dir, dry_run=False)
        if os.access(cap_base, os.W_OK):
            _add(
                checks,
                id="ccd_save_dir",
                category="存储",
                status="ok",
                title="CCD 保存目录",
                detail=f"可写：{cap_base}",
            )
        else:
            _add(
                checks,
                id="ccd_save_dir",
                category="存储",
                status="fail",
                title="CCD 保存目录",
                detail=f"不可写：{cap_base}",
            )
    except OSError as e:
        _add(
            checks,
            id="ccd_save_dir",
            category="存储",
            status="fail",
            title="CCD 保存目录",
            detail=str(e),
        )

    if include_indi_service and indi_available():
        service_lines = indi_status_lines(port=s.indi_port)
        joined = "\n".join(service_lines)
        if "当前无 indiserver" in joined:
            _add(
                checks,
                id="indi_service",
                category="INDI",
                status="fail",
                title="indiserver",
                detail="无运行中的 indiserver（sudo systemctl start indi-telescope.service）",
            )
        else:
            warn_line = next(
                (ln for ln in service_lines if "手动/孤儿" in ln or "不一致" in ln),
                None,
            )
            if warn_line:
                _add(
                    checks,
                    id="indi_service",
                    category="INDI",
                    status="warn",
                    title="indiserver 进程",
                    detail=warn_line.strip(),
                )
            else:
                _add(
                    checks,
                    id="indi_service",
                    category="INDI",
                    status="ok",
                    title="indiserver",
                    detail="systemd 管理运行中",
                )

    if indi_available():
        r = run_getprop(s.indi_host, s.indi_port, "*.*.*", timeout=gp_t)
        if r.returncode != 0:
            _add(
                checks,
                id="indi_reachable",
                category="INDI",
                status="fail",
                title=f"indi_getprop {s.indi_host}:{s.indi_port}",
                detail=(r.stderr or r.stdout or f"exit {r.returncode}").strip()[:200],
            )
        else:
            blob = r.stdout or ""
            _add(
                checks,
                id="indi_reachable",
                category="INDI",
                status="ok",
                title=f"INDI {s.indi_host}:{s.indi_port}",
                detail="indi_getprop 可达",
            )

    # --- Mount ---
    mount_dev = ""
    if blob:
        try:
            mount_dev = resolve_telescope_device(s)
        except Exception as e:
            _add(
                checks,
                id="mount_resolve",
                category="赤道仪",
                status="fail",
                title="设备名解析",
                detail=str(e),
            )
        else:
            if _device_in_getprop(blob, mount_dev):
                conn = _parse_on_off(blob, mount_dev, "CONNECTION", "CONNECT")
                if conn == "On":
                    _add(
                        checks,
                        id="mount_connect",
                        category="赤道仪",
                        status="ok",
                        title=f"{mount_dev} 已连接",
                        detail="CONNECTION.CONNECT=On",
                    )
                else:
                    _add(
                        checks,
                        id="mount_connect",
                        category="赤道仪",
                        status="fail",
                        title=f"{mount_dev} 未连接",
                        detail="执行 telbot mount connect --execute",
                    )
                park = _parse_on_off(blob, mount_dev, "TELESCOPE_PARK", "PARK")
                unpark = _parse_on_off(blob, mount_dev, "TELESCOPE_PARK", "UNPARK")
                if park == "On":
                    _add(
                        checks,
                        id="mount_park",
                        category="赤道仪",
                        status="warn",
                        title="镜架处于 Park",
                        detail="观测前须 telbot mount unpark --execute",
                    )
                elif unpark == "On":
                    _add(
                        checks,
                        id="mount_park",
                        category="赤道仪",
                        status="ok",
                        title="已 Unpark",
                        detail="TELESCOPE_PARK.UNPARK=On",
                    )
                ra = _parse_on_off(blob, mount_dev, "EQUATORIAL_EOD_COORD", "RA")
                if ra is not None:
                    _add(
                        checks,
                        id="mount_coords",
                        category="赤道仪",
                        status="ok",
                        title="赤道坐标可读",
                        detail=f"RA={ra}",
                    )
            else:
                _add(
                    checks,
                    id="mount_presence",
                    category="赤道仪",
                    status="fail",
                    title=f"未找到 {mount_dev!r}",
                    detail="indiserver 中无该设备；检查选镜与 USB",
                )

    ccd_dev = (s.indi_ccd_device or "").strip()
    if blob:
        ccd_dev = resolve_ccd_device_from_getprop_stdout(s, blob)
    _check_optional_device(
        checks,
        blob,
        s,
        device=ccd_dev,
        category="CCD",
        id_prefix="ccd",
        connect_hint="telbot camera connect --execute",
        required_for_ready=True,
    )
    _check_optional_device(
        checks,
        blob,
        s,
        device=(s.indi_cfw_device or "").strip(),
        category="滤镜轮",
        id_prefix="cfw",
        connect_hint="telbot filter connect --execute",
        required_for_ready=False,
    )
    _check_optional_device(
        checks,
        blob,
        s,
        device=(s.indi_focuser_device or "").strip(),
        category="电调",
        id_prefix="focuser",
        connect_hint="telbot focuser connect --execute",
        required_for_ready=False,
        extra_check=_focuser_position_check,
    )

    pwi4_flag = Path("/run/telbot/pwi4_required")
    if pwi4_flag.is_file() and pwi4_flag.read_text(encoding="utf-8").strip() == "1":
        _check_pwi4(checks)

    fails = [c for c in checks if c.status == "fail"]
    ready = len(fails) == 0
    check_dicts = [asdict(c) for c in checks]
    return {
        "ok": ready,
        "ready": ready,
        "action": "preflight",
        "dry_run": True,
        "fail_count": len(fails),
        "warn_count": sum(1 for c in checks if c.status == "warn"),
        "checks": check_dicts,
        "mount_device": mount_dev or None,
        "message": _format_checks_message(checks, ready=ready),
    }


def _focuser_position_check(s: Settings, device: str) -> PreflightCheck | None:
    rc, pos, _ = focuser_get_absolute_position(
        device, s.indi_host, s.indi_port, timeout=s.indi_getprop_timeout
    )
    if rc != 0 or pos is None:
        return PreflightCheck(
            id="focuser_position",
            category="电调",
            status="warn",
            title="位置读取",
            detail="无法读取 ABS_FOCUS_POSITION",
        )
    return PreflightCheck(
        id="focuser_position",
        category="电调",
        status="ok",
        title="当前位置",
        detail=f"{int(pos)} 步",
    )


def _check_optional_device(
    checks: list[PreflightCheck],
    blob: str,
    s: Settings,
    *,
    device: str,
    category: str,
    id_prefix: str,
    connect_hint: str,
    required_for_ready: bool,
    extra_check: Any = None,
) -> None:
    if not device:
        _add(
            checks,
            id=f"{id_prefix}_config",
            category=category,
            status="skip",
            title="未配置",
            detail=f"TELBOT_INDI_{id_prefix.upper()}_DEVICE 为空",
        )
        return
    if not blob:
        return
    if not _device_in_getprop(blob, device):
        _add(
            checks,
            id=f"{id_prefix}_presence",
            category=category,
            status="skip",
            title=device,
            detail="当前 indiserver 未加载该驱动（未插设备或未选镜）",
        )
        return
    if ccd_is_connected if id_prefix == "ccd" else (
        cfw_is_connected if id_prefix == "cfw" else focuser_is_connected
    )(device, s.indi_host, s.indi_port, timeout=max(s.indi_getprop_timeout, 2.0)):
        _add(
            checks,
            id=f"{id_prefix}_connect",
            category=category,
            status="ok",
            title=f"{device} 已连接",
            detail="CONNECTION.CONNECT=On",
        )
        if extra_check is not None:
            extra = extra_check(s, device)
            if extra is not None:
                checks.append(extra)
    else:
        _add(
            checks,
            id=f"{id_prefix}_connect",
            category=category,
            status="fail" if required_for_ready else "warn",
            title=f"{device} 未连接",
            detail=connect_hint,
        )


def _check_pwi4(checks: list[PreflightCheck]) -> None:
    url = os.environ.get("TELBOT_PWI4_HTTP_URL", "http://127.0.0.1:8220").rstrip("/")
    try:
        with urllib.request.urlopen(f"{url}/status", timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        _add(
            checks,
            id="pwi4_http",
            category="PlaneWave",
            status="fail",
            title="PWI4 HTTP",
            detail=f"{url}/status 不可达：{e}",
        )
        return
    if re.search(r"mount\.is_connected\s*=\s*true", body, re.I) or "mount.is_connected\":true" in body:
        _add(
            checks,
            id="pwi4_mount",
            category="PlaneWave",
            status="ok",
            title="PWI4 mount",
            detail="mount.is_connected=true",
        )
    else:
        _add(
            checks,
            id="pwi4_mount",
            category="PlaneWave",
            status="fail",
            title="PWI4 mount 未连接",
            detail="选镜后须 mount/connect；见 docs/MOUNT_AUTO.md PlaneWave 专节",
        )
