"""INDI server process hygiene (systemd vs manual ``indiserver`` in SSH)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _run(cmd: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def indi_status_lines(
    *,
    unit: str | None = None,
    port: int | None = None,
    args_path: Path | None = None,
) -> list[str]:
    unit = (unit or os.environ.get("TELBOT_INDI_SYSTEMD_UNIT") or "indi-telescope.service").strip()
    port = port if port is not None else int(os.environ.get("TELBOT_INDI_PORT", "7624"))
    args_path = args_path or Path("/run/telbot/indiserver.args")

    lines: list[str] = []
    want = ""
    if args_path.is_file():
        want = args_path.read_text(encoding="utf-8").strip().splitlines()[0]
    lines.append(f"期望 indiserver 参数（{args_path}）：{want or '(空)'}")

    st = _run(["systemctl", "is-active", unit], timeout=15)
    lines.append(f"systemd {unit}：{(st.stdout or st.stderr).strip() or 'unknown'}")

    main_pid = "0"
    show = _run(["systemctl", "show", "-p", "MainPID", "--value", unit], timeout=15)
    if show.returncode == 0 and (show.stdout or "").strip():
        main_pid = (show.stdout or "").strip()

    procs = _run(["pgrep", "-a", "-x", "indiserver"], timeout=15)
    if procs.returncode != 0 or not (procs.stdout or "").strip():
        lines.append("当前无 indiserver 进程。")
        return lines

    for row in (procs.stdout or "").strip().splitlines():
        pid_s = row.split(None, 1)[0]
        cmd = row.split(None, 1)[1] if " " in row else row
        tag = "systemd" if pid_s == main_pid else "手动/孤儿（会刷 SSH 日志，拔 USB 不会停）"
        lines.append(f"pid {pid_s} [{tag}]：{cmd}")
        if want and want not in cmd:
            lines.append("  ⚠ 与 indiserver.args 不一致，请执行：telbot indi stop && sudo telbot-select-mount.sh")

    return lines


def indi_stop(*, unit: str | None = None, port: int | None = None) -> list[str]:
    """Stop systemd unit and any indiserver on INDI port."""
    unit = (unit or os.environ.get("TELBOT_INDI_SYSTEMD_UNIT") or "indi-telescope.service").strip()
    port = port if port is not None else int(os.environ.get("TELBOT_INDI_PORT", "7624"))
    msgs: list[str] = []

    _run(["systemctl", "stop", unit], timeout=120)
    msgs.append(f"已 systemctl stop {unit}")

    if _run(["which", "fuser"], timeout=5).returncode == 0:
        _run(["fuser", "-k", f"{port}/tcp"], timeout=15)
        msgs.append(f"已释放端口 {port}（fuser）")
    else:
        _run(["pkill", "-x", "indiserver"], timeout=15)
        msgs.append("已 pkill indiserver")

    left = _run(["pgrep", "-a", "-x", "indiserver"], timeout=15)
    if left.returncode == 0 and (left.stdout or "").strip():
        msgs.append(f"仍有进程：{(left.stdout or '').strip()}")
    else:
        msgs.append("当前无 indiserver 进程。")
    return msgs


def find_select_mount_script() -> str | None:
    for path in (
        "/usr/local/bin/telbot-select-mount.sh",
        "/usr/local/lib/telbot-deploy/telbot-select-mount.sh",
    ):
        if os.access(path, os.X_OK):
            return path
    return None
