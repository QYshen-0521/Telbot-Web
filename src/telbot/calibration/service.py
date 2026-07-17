"""HTTP / App cooperative stop for multi-frame calibration capture."""

from __future__ import annotations

from telbot.repo_paths import calibration_abort_flag_path
from telbot.scheduling.abort import AbortController


def request_calibration_abort(reason: str = "http_stop") -> None:
    flag = calibration_abort_flag_path()
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text(reason.strip() or "abort", encoding="utf-8")


def clear_calibration_abort_flag() -> None:
    p = calibration_abort_flag_path()
    if p.is_file():
        p.unlink()


def calibration_abort_controller() -> AbortController:
    return AbortController(flag_path=calibration_abort_flag_path())
