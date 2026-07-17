from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from telbot import http_serve


def test_serve_host_restart_default(monkeypatch):
    monkeypatch.delenv("TELBOT_SERVE_HOST", raising=False)
    assert http_serve.serve_host() == "127.0.0.1"
    assert http_serve.serve_host(restart=True) == "0.0.0.0"
    monkeypatch.setenv("TELBOT_SERVE_HOST", "192.168.1.10")
    assert http_serve.serve_host(restart=True) == "192.168.1.10"


def test_pids_on_tcp_port_parses_ss():
    stdout = "LISTEN 0 128 127.0.0.1:8765 0.0.0.0:* users:((\"python\",pid=4242,fd=3))"
    with patch.object(http_serve.shutil, "which", return_value="/usr/bin/ss"):
        with patch.object(http_serve, "_run") as run:
            run.return_value = MagicMock(returncode=0, stdout=stdout)
            assert http_serve._pids_on_tcp_port(8765) == [4242]


def test_stop_http_serve_kills_pid_file(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    pid_file = run_dir / "telbot-serve.pid"
    monkeypatch.setattr(http_serve, "serve_pid_path", lambda: pid_file)
    monkeypatch.setattr(http_serve, "run_state_dir", lambda: run_dir)
    pid_file.write_text("99999\n", encoding="utf-8")

    killed: list[int] = []

    def fake_kill(pid: int, *, force: bool = False) -> bool:
        killed.append(pid)
        return True

    alive = {99999}

    def pid_alive(pid: int) -> bool:
        return pid in alive

    def fake_kill_pid(pid: int, *, force: bool = False) -> bool:
        killed.append(pid)
        alive.discard(pid)
        return True

    monkeypatch.setattr(http_serve, "_pid_alive", pid_alive)
    monkeypatch.setattr(http_serve, "_kill_pid", fake_kill_pid)
    monkeypatch.setattr(http_serve, "_pids_on_tcp_port", lambda _port: [])
    monkeypatch.setattr(http_serve.shutil, "which", lambda _cmd: None)

    msgs = http_serve.stop_http_serve(port=8765)
    assert 99999 in killed
    assert not pid_file.exists()
    assert any("8765" in m for m in msgs)


def test_check_health_quick_url():
    payload = json.dumps({"status": "ok", "version": "0.4.0"}).encode()

    class Resp:
        status = 200

        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch.object(http_serve.urllib.request, "urlopen", return_value=Resp()) as urlopen:
        http_serve.check_health(host="0.0.0.0", port=8765, quick=True)
        req = urlopen.call_args[0][0]
        called_url = req.full_url if hasattr(req, "full_url") else str(req)
        assert "quick=1" in called_url


def test_check_health_ok():
    payload = json.dumps({"status": "ok", "version": "0.4.0"}).encode()

    class Resp:
        status = 200

        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch.object(http_serve.urllib.request, "urlopen", return_value=Resp()):
        out = http_serve.check_health(host="127.0.0.1", port=8765)
    assert out["ok"] is True
    assert out["body"]["version"] == "0.4.0"


def test_restart_http_serve_sequence(monkeypatch, tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.setattr(http_serve, "run_state_dir", lambda: run_dir)
    monkeypatch.setattr(http_serve, "serve_pid_path", lambda: run_dir / "telbot-serve.pid")
    monkeypatch.setattr(http_serve, "serve_log_path", lambda: run_dir / "telbot-serve.log")

    calls: list[str] = []

    monkeypatch.setattr(http_serve, "stop_http_serve", lambda **kw: ["stopped"])
    monkeypatch.setattr(
        http_serve,
        "start_http_serve_background",
        lambda **kw: (calls.append("start") or ["started pid=1"]),
    )
    monkeypatch.setattr(
        http_serve,
        "wait_for_health",
        lambda **kw: {"ok": True, "body": {"version": "0.4.0"}},
    )

    msgs = http_serve.restart_http_serve(host="0.0.0.0", port=8765, reinstall=False)
    assert "stopped" in msgs
    assert calls == ["start"]
    assert any("健康检查通过" in m for m in msgs)


def test_restart_fails_when_health_bad(monkeypatch, tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.setattr(http_serve, "run_state_dir", lambda: run_dir)
    monkeypatch.setattr(http_serve, "stop_http_serve", lambda **kw: [])
    monkeypatch.setattr(http_serve, "start_http_serve_background", lambda **kw: ["started"])
    monkeypatch.setattr(http_serve, "wait_for_health", lambda **kw: {"ok": False, "error": "refused"})

    with pytest.raises(RuntimeError, match="health"):
        http_serve.restart_http_serve(wait_health=True)
