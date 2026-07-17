"""Telbot HTTP API (uvicorn) process management for Pi / App debugging."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from telbot.repo_paths import run_state_dir, telbot_repo_root

DEFAULT_HOST = "127.0.0.1"
DEFAULT_HOST_RESTART = "0.0.0.0"
DEFAULT_PORT = 8765
HEALTH_PATH = "/health"


def serve_host(*, restart: bool = False) -> str:
    raw = os.environ.get("TELBOT_SERVE_HOST", "").strip()
    if raw:
        return raw
    return DEFAULT_HOST_RESTART if restart else DEFAULT_HOST


def serve_port() -> int:
    raw = os.environ.get("TELBOT_SERVE_PORT", str(DEFAULT_PORT)).strip()
    return int(raw)


def serve_pid_path() -> Path:
    return run_state_dir() / "telbot-serve.pid"


def serve_log_path() -> Path:
    return run_state_dir() / "telbot-serve.log"


def _run(cmd: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _pids_on_tcp_port(port: int) -> list[int]:
    pids: list[int] = []
    if shutil.which("ss"):
        cp = _run(["ss", "-tlnp", f"sport = :{port}"], timeout=15)
        if cp.returncode == 0 and cp.stdout:
            for m in re.finditer(r"pid=(\d+)", cp.stdout):
                pids.append(int(m.group(1)))
    if not pids and shutil.which("fuser"):
        cp = _run(["fuser", f"{port}/tcp"], timeout=15)
        # fuser prints: 8765/tcp:  1234 5678
        if cp.returncode in (0, 1) and (cp.stdout or "").strip():
            for tok in re.split(r"\D+", (cp.stdout or "").strip()):
                if tok.isdigit():
                    pids.append(int(tok))
    return sorted(set(pids))


def _read_pid_file() -> int | None:
    path = serve_pid_path()
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip().splitlines()[0])
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _kill_pid(pid: int, *, force: bool = False) -> bool:
    if not _pid_alive(pid):
        return False
    try:
        os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
    except OSError:
        return False
    return True


def _kill_pids(pids: list[int], *, wait_s: float = 2.0) -> list[int]:
    remaining = [p for p in pids if _pid_alive(p)]
    for pid in remaining:
        _kill_pid(pid)
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        remaining = [p for p in remaining if _pid_alive(p)]
        if not remaining:
            break
        time.sleep(0.15)
    for pid in remaining:
        _kill_pid(pid, force=True)
    return [p for p in pids if _pid_alive(p)]


def stop_http_serve(*, port: int | None = None, clear_pid: bool = True) -> list[str]:
    """Stop listeners on the HTTP port and optional pid-file process."""
    port = port if port is not None else serve_port()
    msgs: list[str] = []
    targets: list[int] = []

    pid_file = _read_pid_file()
    if pid_file is not None:
        targets.append(pid_file)
        msgs.append(f"pid 文件 {serve_pid_path()}：{pid_file}")

    targets.extend(_pids_on_tcp_port(port))
    targets = sorted(set(targets))

    if not targets:
        msgs.append(f"端口 {port} 上无 Telbot HTTP 进程。")
    else:
        left = _kill_pids(targets)
        if left:
            msgs.append(f"仍有进程未退出：{left}")
        else:
            msgs.append(f"已停止端口 {port} 上的进程：{targets}")

    if clear_pid and serve_pid_path().is_file():
        try:
            serve_pid_path().unlink()
        except OSError:
            pass
        msgs.append("已清除 pid 文件。")

    if shutil.which("fuser"):
        _run(["fuser", "-k", f"{port}/tcp"], timeout=15)

    return msgs


def _health_url(host: str, port: int, *, quick: bool = False) -> str:
    bind = host if host not in ("0.0.0.0", "::") else "127.0.0.1"
    url = f"http://{bind}:{port}{HEALTH_PATH}"
    if quick:
        url += "?quick=1"
    return url


def _health_probe_timeout_s(*, quick: bool) -> float:
    if quick:
        return float(os.environ.get("TELBOT_SERVE_HEALTH_QUICK_TIMEOUT", "5"))
    raw = os.environ.get("TELBOT_SERVE_HEALTH_TIMEOUT", "").strip()
    if raw:
        return max(3.0, float(raw))
    return max(15.0, float(os.environ.get("TELBOT_HEALTH_GETPROP_MAX_S", "12")) + 5.0)


def check_health(
    *,
    host: str | None = None,
    port: int | None = None,
    timeout_s: float | None = None,
    quick: bool = False,
) -> dict:
    host = host if host is not None else serve_host()
    port = port if port is not None else serve_port()
    if timeout_s is None:
        timeout_s = _health_probe_timeout_s(quick=quick)
    url = _health_url(host, port, quick=quick)
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {"raw": body}
            return {"ok": True, "url": url, "status": resp.status, "body": data}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"ok": False, "url": url, "error": str(e)}


def http_serve_status_lines(*, host: str | None = None, port: int | None = None) -> list[str]:
    host = host if host is not None else serve_host()
    port = port if port is not None else serve_port()
    lines = [f"HTTP 绑定：{host}:{port}（环境变量 TELBOT_SERVE_HOST / TELBOT_SERVE_PORT）"]
    lines.append(f"日志：{serve_log_path()}")
    lines.append(f"pid 文件：{serve_pid_path()}")

    pid_file = _read_pid_file()
    if pid_file is not None:
        alive = _pid_alive(pid_file)
        lines.append(f"pid 文件记录：{pid_file}（{'运行中' if alive else '已退出'}）")

    port_pids = _pids_on_tcp_port(port)
    if port_pids:
        lines.append(f"监听端口 {port} 的进程：{port_pids}")
    else:
        lines.append(f"端口 {port} 无监听。")

    health = check_health(host=host, port=port)
    if health.get("ok"):
        ver = (health.get("body") or {}).get("version", "?")
        lines.append(f"GET {health['url']}：OK（version={ver}）")
    else:
        lines.append(f"GET {health.get('url', _health_url(host, port))}：失败（{health.get('error', '?')}）")
    return lines


def _telbot_cli_argv(host: str, port: int) -> list[str]:
    exe = shutil.which("telbot")
    if exe:
        return [exe, "serve", "--host", host, "--port", str(port)]
    return [sys.executable, "-m", "telbot", "serve", "--host", host, "--port", str(port)]


def _resolve_repo_for_reinstall() -> Path | None:
    explicit = os.environ.get("TELBOT_REPO", "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        if (p / "pyproject.toml").is_file():
            return p.resolve()
    for candidate in (Path.cwd(), telbot_repo_root(), Path.home() / "Telbot"):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "telbot").is_dir():
            return candidate.resolve()
    return None


def reinstall_editable_package() -> list[str]:
    repo = _resolve_repo_for_reinstall()
    if repo is None:
        return ["跳过 pip install：未找到含 pyproject.toml 的 Telbot 目录（可设 TELBOT_REPO）。"]
    cp = _run(
        [sys.executable, "-m", "pip", "install", "-e", "."],
        timeout=600,
    )
    msgs = [f"已在 {repo} 执行：{sys.executable} -m pip install -e ."]
    if cp.returncode != 0:
        err = (cp.stderr or cp.stdout or "").strip() or f"exit {cp.returncode}"
        msgs.append(f"pip 失败：{err}")
        raise RuntimeError(err)
    tail = (cp.stdout or "").strip().splitlines()
    if tail:
        msgs.append(tail[-1])
    return msgs


def start_http_serve_background(
    *,
    host: str | None = None,
    port: int | None = None,
) -> list[str]:
    host = host if host is not None else serve_host()
    port = port if port is not None else serve_port()
    run_state_dir().mkdir(parents=True, exist_ok=True)
    log_path = serve_log_path()
    pid_path = serve_pid_path()

    log_f = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
    try:
        proc = subprocess.Popen(
            _telbot_cli_argv(host, port),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=str(_resolve_repo_for_reinstall() or Path.cwd()),
        )
    except OSError as e:
        log_f.close()
        raise RuntimeError(f"无法启动 telbot serve：{e}") from e

    pid_path.write_text(f"{proc.pid}\n", encoding="utf-8")
    return [
        f"已在后台启动 pid={proc.pid}",
        f"命令：{' '.join(_telbot_cli_argv(host, port))}",
        f"日志：{log_path}",
        f"健康检查：{_health_url(host, port, quick=True)}",
    ]


def wait_for_health(
    *,
    host: str | None = None,
    port: int | None = None,
    timeout_s: float = 25.0,
    interval_s: float = 0.4,
    quick: bool = True,
) -> dict:
    """Wait until HTTP is up. Default *quick* probe skips INDI in ``/health``."""
    deadline = time.monotonic() + timeout_s
    last: dict = {"ok": False}
    probe_timeout = _health_probe_timeout_s(quick=quick)
    # Give uvicorn a moment to bind after background start.
    time.sleep(0.35)
    while time.monotonic() < deadline:
        last = check_health(host=host, port=port, timeout_s=probe_timeout, quick=quick)
        if last.get("ok"):
            return last
        time.sleep(interval_s)
    return last


def restart_http_serve(
    *,
    host: str | None = None,
    port: int | None = None,
    reinstall: bool = False,
    wait_health: bool = True,
) -> list[str]:
    """Stop existing listener, optionally pip install -e ., start background serve."""
    host = host if host is not None else serve_host(restart=True)
    port = port if port is not None else serve_port()
    msgs: list[str] = ["=== 停止旧 HTTP 服务 ==="]
    msgs.extend(stop_http_serve(port=port))
    if reinstall:
        msgs.append("=== 更新 Python 包（editable）===")
        msgs.extend(reinstall_editable_package())
    msgs.append("=== 启动新 HTTP 服务 ===")
    msgs.extend(start_http_serve_background(host=host, port=port))
    if wait_health:
        health = wait_for_health(host=host, port=port)
        if health.get("ok"):
            ver = (health.get("body") or {}).get("version", "?")
            msgs.append(f"健康检查通过（version={ver}）。")
        else:
            msgs.append(
                f"健康检查未通过：{health.get('error', '?')}；"
                f"请查看日志 {serve_log_path()}"
            )
            raise RuntimeError("telbot serve 启动后 /health 不可用")
    return msgs
