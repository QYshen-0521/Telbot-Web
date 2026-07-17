"""Paths relative to the Telbot repository root (directory containing `src/telbot`)."""

from __future__ import annotations

from pathlib import Path


def telbot_package_dir() -> Path:
    return Path(__file__).resolve().parent


def telbot_repo_root() -> Path:
    """Project root: parent of `src/`."""
    return telbot_package_dir().parent.parent


def data_dir() -> Path:
    return telbot_repo_root() / "data"


def ccd_captures_dir() -> Path:
    """INDI UPLOAD_DIR should point here (see README)."""
    return data_dir() / "ccd_captures"


def platesolve_dir() -> Path:
    return data_dir() / "platesolve"


def platesolve_in_dir() -> Path:
    return platesolve_dir() / "in"


def platesolve_out_dir() -> Path:
    return platesolve_dir() / "out"


def platesolve_logs_dir() -> Path:
    return platesolve_dir() / "logs"


def platesolve_index_dir() -> Path:
    return platesolve_dir() / "index"


def platesolve_last_solve_json() -> Path:
    return platesolve_dir() / "last_solve.json"


def plans_dir() -> Path:
    """Saved observing plans (JSON); gitignored."""
    return data_dir() / "plans"


def pending_dir() -> Path:
    """Multi-turn intent state (e.g. last exoplanet transit list)."""
    return data_dir() / "pending"


def run_state_dir() -> Path:
    """Runtime state for long-running CLI jobs (abort flag, session); gitignored."""
    return data_dir() / "run"


def transit_abort_flag_path() -> Path:
    """Out-of-band abort flag watched by `telbot plan transit-run`."""
    return run_state_dir() / "transit_abort.flag"


def transit_run_session_path() -> Path:
    """Session info (pid/plan) of the active `telbot plan transit-run`."""
    return run_state_dir() / "transit_run.json"


def last_transit_ingress_precheck_path() -> Path:
    """Latest ingress pre-check result (App polls via HTTP)."""
    return run_state_dir() / "last_transit_ingress_precheck.json"


def live_stack_status_path() -> Path:
    """Current / last live-stack session status (JSON for App polling)."""
    return run_state_dir() / "live_stack_status.json"


def live_stack_preview_jpeg_path() -> Path:
    """Latest stacked preview JPEG (App ``GET /camera/live-stack/preview``)."""
    return run_state_dir() / "live_stack_preview.jpg"


def snap_preview_jpeg_path() -> Path:
    """Latest single-snap preview JPEG (App ``GET /camera/snap/preview``)."""
    return run_state_dir() / "snap_preview.jpg"


def snap_last_meta_path() -> Path:
    """Last snap FITS path + preview status (``GET /camera/snap/preview`` lazy regen)."""
    return run_state_dir() / "snap_last.json"


def live_stack_abort_flag_path() -> Path:
    """Out-of-band abort for ``telbot camera live-stack`` / HTTP stop."""
    return run_state_dir() / "live_stack_abort.flag"


def calibration_abort_flag_path() -> Path:
    """Out-of-band abort for ``POST /camera/cal/stop`` during multi-frame calibration."""
    return run_state_dir() / "calibration_abort.flag"


def ensure_platesolve_layout() -> None:
    for p in (
        ccd_captures_dir(),
        platesolve_in_dir(),
        platesolve_out_dir(),
        platesolve_logs_dir(),
        platesolve_index_dir(),
        plans_dir(),
    ):
        p.mkdir(parents=True, exist_ok=True)
