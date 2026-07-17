"""Background live-stack worker for HTTP API."""

from __future__ import annotations

import threading
from typing import Any

from telbot.config import Settings
from telbot.live_stack.runner import run_live_stack
from telbot.repo_paths import live_stack_abort_flag_path, live_stack_status_path
from telbot.scheduling.abort import AbortController


_live_stack_thread: threading.Thread | None = None
_live_stack_last_result: dict[str, Any] | None = None


def live_stack_is_running() -> bool:
    return _live_stack_thread is not None and _live_stack_thread.is_alive()


def read_live_stack_status() -> dict[str, Any]:
    path = live_stack_status_path()
    if not path.is_file():
        return {
            "ok": True,
            "running": live_stack_is_running(),
            "schema_version": "telbot.live_stack.v1",
            "message": "尚无边拍边叠会话",
        }
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data["running"] = live_stack_is_running()
    if _live_stack_last_result is not None and not data.get("running"):
        data.setdefault("last_result", _live_stack_last_result)
    return data


def request_live_stack_abort(reason: str = "http_abort") -> None:
    flag = live_stack_abort_flag_path()
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text(reason.strip() or "abort", encoding="utf-8")


def _clear_abort_flag() -> None:
    p = live_stack_abort_flag_path()
    if p.is_file():
        p.unlink()


def _abort_controller() -> AbortController:
    return AbortController(flag_path=live_stack_abort_flag_path())


def start_live_stack_background(
    s: Settings,
    *,
    duration_seconds: float,
    exposure_seconds: float | None,
    cadence_seconds: float | None,
    session_tag: str | None,
    cal_bias_dir: str | None = None,
    cal_dark_dir: str | None = None,
    cal_flat_dir: str | None = None,
    execute: bool,
) -> dict[str, Any]:
    global _live_stack_thread, _live_stack_last_result

    if live_stack_is_running():
        return {"ok": False, "error": "live_stack_already_active"}

    if not execute:
        return run_live_stack(
            s,
            duration_seconds=duration_seconds,
            exposure_seconds=exposure_seconds,
            cadence_seconds=cadence_seconds,
            session_tag=session_tag,
            cal_bias_dir=cal_bias_dir,
            cal_dark_dir=cal_dark_dir,
            cal_flat_dir=cal_flat_dir,
            execute=False,
        )

    _clear_abort_flag()

    def _worker() -> None:
        global _live_stack_last_result
        try:
            out = run_live_stack(
                s,
                duration_seconds=duration_seconds,
                exposure_seconds=exposure_seconds,
                cadence_seconds=cadence_seconds,
                session_tag=session_tag,
                cal_bias_dir=cal_bias_dir,
                cal_dark_dir=cal_dark_dir,
                cal_flat_dir=cal_flat_dir,
                execute=True,
                abort=_abort_controller(),
            )
            _live_stack_last_result = out
        except Exception as e:
            _live_stack_last_result = {
                "ok": False,
                "error": str(e),
                "action": "live_stack",
            }
        finally:
            _clear_abort_flag()

    _live_stack_thread = threading.Thread(target=_worker, name="telbot-live-stack", daemon=True)
    _live_stack_thread.start()
    return {
        "ok": True,
        "started": True,
        "schema_version": "telbot.live_stack.v1",
        "duration_seconds": duration_seconds,
        "exposure_seconds": exposure_seconds,
        "session_tag": session_tag,
        "preview_url": "/camera/live-stack/preview",
        "status_url": "/camera/live-stack/status",
        "message": "边拍边叠已在后台启动",
    }


def stop_live_stack() -> dict[str, Any]:
    if not live_stack_is_running():
        return {"ok": True, "stopped": False, "message": "无运行中的边拍边叠"}
    request_live_stack_abort("user_stop")
    return {"ok": True, "stopped": True, "message": "已请求中止边拍边叠"}
