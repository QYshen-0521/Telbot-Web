#!/usr/bin/env python3
"""
Select INDI drivers from USB identity + deploy/mount_profiles.json.
Writes /run/telbot/indiserver.args, indi_device_hint, mount_profile_id.

Restart indiserver via systemd is done by telbot-select-mount.sh *outside* flock
(TELBOT_SELECT_MOUNT_DEFER_RESTART=1) to avoid deadlock with indi-telescope.service
ExecStartPre (which uses TELBOT_SELECT_MOUNT_TRY_LOCK=1 + flock -n).

Env:
  TELBOT_MOUNT_PROFILES   Path to mount_profiles.json (default: alongside this script)
  TELBOT_INDI_SYSTEMD_UNIT  Unit to restart (default: indi-telescope.service; direct python only)
  TELBOT_SELECT_MOUNT_DRY_RUN  If "1", only print actions, no write/restart
  TELBOT_SELECT_MOUNT_WRITE_ENV  Set "0" to skip .env sync (default: write)
  TELBOT_SELECT_MOUNT_NO_RESTART  If "1", never systemctl restart from this process
  TELBOT_SELECT_MOUNT_DEFER_RESTART  If "1" with NO_RESTART: exit 2 when files changed (shell restarts)
  TELBOT_SELECT_MOUNT_AUTO_CONNECT  If "0", skip CONNECTION.CONNECT after restart (default: on)
  TELBOT_INDI_HOST / TELBOT_INDI_PORT  INDI for auto-connect (default 127.0.0.1:7624)
  TELBOT_ENV_FILE  Target .env for sync (see telbot.env_sync.resolve_dotenv_path)

Exit codes: 0 ok, 1 error, 2 ok and caller should systemctl restart (only with DEFER_RESTART).

When no ``profiles[]`` row matches current USB, ``mount_profiles.json`` may define top-level
``on_no_usb_match`` (see docs/MOUNT_AUTO.md). Default shipped manifest uses ``action: restart``
with ``indi_simulator_telescope`` so ``telbot-select-mount.sh`` still refreshes indiserver
after unplugging all astronomy USB (optional drivers like SBIG drop off the argv).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

RUN = Path("/run/telbot")
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MANIFEST = SCRIPT_DIR / "mount_profiles.json"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_RESTART_NEEDED = 2


def _apply_udev_removed_vidpids(vidpids: set[str]) -> set[str]:
    """
    udev ACTION=remove 时 ``lsusb`` 常仍短暂列出已拔设备；用 ``TELBOT_UDEV_REMOVED_VIDPID`` 剔除。
    """
    raw = os.environ.get("TELBOT_UDEV_REMOVED_VIDPID", "").strip().lower()
    if not raw or ":" not in raw:
        return vidpids
    out = set(vidpids)
    out.discard(raw)
    # QHY174：引导 c174 / 工作 c175 成对剔除
    if raw in ("1618:c175", "1618:c174") or raw.startswith("1618:"):
        out.discard("1618:c174")
        out.discard("1618:c175")
    print(
        f"udev remove: ignore {raw!r} in lsusb snapshot (remaining {sorted(out) or 'none'})",
        file=sys.stderr,
    )
    return out


def _lsusb_vid_pids() -> set[str]:
    try:
        r = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return set()
    if r.returncode != 0:
        return set()
    out: set[str] = set()
    for line in r.stdout.splitlines():
        m = re.search(r"ID ([0-9a-fA-F]{4}):([0-9a-fA-F]{4})", line)
        if m:
            out.add(f"{m.group(1).lower()}:{m.group(2).lower()}")
    return out


def _by_id_strings() -> list[str]:
    base = Path("/dev/serial/by-id")
    if not base.is_dir():
        return []
    return [p.name for p in base.iterdir() if p.is_symlink()]


def _profile_matches(p: dict, vidpids: set[str], by_ids: list[str]) -> bool:
    m = p.get("match") or {}
    mode = (p.get("match_mode") or "any").strip().lower()
    vid = (m.get("usb_vid_pid") or "").strip().lower()
    sub = (m.get("by_id_substring") or "").strip()
    ok_vid = bool(vid and vid in vidpids)
    ok_sub = bool(sub and any(sub in s for s in by_ids))
    if not vid and not sub:
        return False
    if mode == "all":
        if vid and not ok_vid:
            return False
        if sub and not ok_sub:
            return False
        return True
    return ok_vid or ok_sub


def select_profile(data: dict, vidpids: set[str], by_ids: list[str]) -> dict | None:
    profiles = data.get("profiles") or []
    matches = [p for p in profiles if _profile_matches(p, vidpids, by_ids)]
    if not matches:
        return None
    return max(matches, key=lambda x: int(x.get("priority") or 0))


def _optional_indi_drivers_resolved(prof: dict, vidpids: set[str], by_ids: list[str]) -> list[str]:
    """
    If profile defines ``optional_indi_if`` (list of {match, match_mode?, indi_drivers}),
    append drivers only when that block's match hits current USB.

    If ``optional_indi_if`` is absent, fall back to legacy ``optional_indi_drivers`` (always appended).
    """
    blocks = prof.get("optional_indi_if")
    if blocks is not None:
        out: list[str] = []
        for block in blocks:
            m = block.get("match") or {}
            mode = (block.get("match_mode") or "any").strip().lower()
            syn = {"match": m, "match_mode": mode}
            if _profile_matches(syn, vidpids, by_ids):
                out.extend(block.get("indi_drivers") or [])
        return out
    return list(prof.get("optional_indi_drivers") or [])


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _load_indi_auto_connect():
    """Prefer deploy-bundled lite module (works under udev/root without venv)."""
    candidates = (
        SCRIPT_DIR / "indi_auto_connect_lite.py",
        SCRIPT_DIR.parent / "src" / "telbot" / "indi_auto_connect.py",
        Path.home() / "Telbot" / "src" / "telbot" / "indi_auto_connect.py",
    )
    for path in candidates:
        if not path.is_file():
            continue
        mod_name = "telbot_indi_auto_connect_lite" if "lite" in path.name else "telbot_indi_auto_connect"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            if not spec or not spec.loader:
                continue
            mod = importlib.util.module_from_spec(spec)
            # Required before exec_module when the file uses @dataclass (else NoneType __dict__).
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            return mod.collect_connect_jobs, mod.run_auto_connect_jobs, mod
        except Exception as e:
            print(f"Warning: failed to load {path}: {e}", file=sys.stderr)
    try:
        from telbot.indi_auto_connect import (
            collect_connect_jobs,
            run_auto_connect_jobs,
        )
        import telbot.indi_auto_connect as mod

        return collect_connect_jobs, run_auto_connect_jobs, mod
    except ImportError:
        pass
    return None, None, None


def _auto_connect_enabled() -> bool:
    return os.environ.get("TELBOT_SELECT_MOUNT_AUTO_CONNECT", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def _indi_host_port() -> tuple[str, int]:
    host = os.environ.get("TELBOT_INDI_HOST", "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(os.environ.get("TELBOT_INDI_PORT", "7624").strip() or "7624")
    except ValueError:
        port = 7624
    return host, port


def _profile_requires_pwi4(prof: dict) -> bool:
    if prof.get("requires_pwi4"):
        return True
    pid = (prof.get("id") or "").strip()
    return pid.startswith("planewave_")


def _write_pwi4_required_flag(required: bool) -> None:
    path = RUN / "pwi4_required"
    if required:
        RUN.mkdir(parents=True, exist_ok=True)
        path.write_text("1\n", encoding="utf-8")
    elif path.is_file():
        path.unlink()


def _save_auto_connect_plan(
    jobs: list[tuple[str, str]],
    host: str,
    port: int,
    *,
    pre_connect_setprop: list[str] | None = None,
) -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "host": host,
        "port": port,
        "jobs": [[drv, dev] for drv, dev in jobs],
    }
    if pre_connect_setprop:
        payload["pre_connect_setprop"] = pre_connect_setprop
    (RUN / "auto_connect.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=0) + "\n",
        encoding="utf-8",
    )


def _pre_connect_setprops(manifest_data: dict, jobs: list[tuple[str, str]]) -> list[str]:
    _collect, _, mod = _load_indi_auto_connect()
    if mod is not None and hasattr(mod, "collect_pre_connect_setprops"):
        return mod.collect_pre_connect_setprops(manifest_data, jobs)
    return []


def _save_auto_connect_plan_from_profile(
    manifest_data: dict,
    prof: dict,
    args_line: str,
    vidpids: set[str],
    by_ids: list[str],
) -> None:
    """Write /run/telbot/auto_connect.json for shell --post-restart-auto-connect."""
    if not _auto_connect_enabled():
        return
    collect_fn, _ = _load_indi_auto_connect()[:2]
    if collect_fn is None:
        return
    host, port = _indi_host_port()
    jobs = collect_fn(
        manifest_data,
        prof,
        args_line,
        vidpids,
        by_ids,
        profile_matches_fn=_profile_matches,
        optional_drivers_resolved_fn=_optional_indi_drivers_resolved,
    )
    if jobs:
        pre = _pre_connect_setprops(manifest_data, jobs)
        _save_auto_connect_plan(jobs, host, port, pre_connect_setprop=pre or None)


def _run_auto_connect_after_restart(
    data: dict,
    prof: dict,
    args_line: str,
    vidpids: set[str],
    by_ids: list[str],
    *,
    dry: bool,
) -> None:
    if dry or not _auto_connect_enabled():
        return
    collect_fn, run_fn, _mod = _load_indi_auto_connect()
    if collect_fn is None or run_fn is None:
        print("Warning: indi_auto_connect not available; skip auto CONNECT", file=sys.stderr)
        return
    host, port = _indi_host_port()
    jobs = collect_fn(
        data,
        prof,
        args_line,
        vidpids,
        by_ids,
        profile_matches_fn=_profile_matches,
        optional_drivers_resolved_fn=_optional_indi_drivers_resolved,
    )
    if not jobs:
        return
    print(f"Auto-connecting {len(jobs)} INDI device(s) on {host}:{port}…", file=sys.stderr)
    pre = _pre_connect_setprops(data, jobs)
    results = run_fn(jobs, host, port, dry_run=False, pre_connect_setprop=pre or None)
    for drv, dev, r in results:
        if r.returncode != 0:
            print(
                f"Warning: auto-connect {dev!r} ({drv}) failed: {r.stderr or r.stdout}",
                file=sys.stderr,
            )
        else:
            print(f"Auto-connected {dev!r} ({drv})", file=sys.stderr)


def _load_env_sync():
    try:
        from telbot.env_sync import resolve_dotenv_path, update_dotenv_keys

        return resolve_dotenv_path, update_dotenv_keys
    except ImportError:
        pass
    candidates = (
        SCRIPT_DIR / "env_sync.py",
        SCRIPT_DIR.parent / "src" / "telbot" / "env_sync.py",
        Path.home() / "Telbot" / "src" / "telbot" / "env_sync.py",
    )
    for repo_env_sync in candidates:
        if repo_env_sync.is_file():
            spec = importlib.util.spec_from_file_location("telbot_env_sync", repo_env_sync)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod.resolve_dotenv_path, mod.update_dotenv_keys
    raise ImportError("telbot.env_sync not available (install telbot or run from repo)")


def _build_dotenv_mapping(
    prof: dict,
    manifest_data: dict,
    args_line: str,
    vidpids: set[str],
    by_ids: list[str],
) -> dict[str, str]:
    """
    Keys to write into .env after profile selection.

    Mount: ``telbot_env_sync`` + ``device_name_hint``.
    CCD / 滤镜轮 / 电调: ``telbot_env_keys`` on profile and/or ``auto_connect_by_driver[].env``
    for each ``indi_*`` driver present in ``args_line``.
    """
    mapping: dict[str, str] = {}
    for key, val in (prof.get("telbot_env_keys") or {}).items():
        k = str(key).strip()
        v = str(val).strip() if val is not None else ""
        if k and v:
            mapping[k] = v

    if prof.get("telbot_env_sync") is not False:
        hint = (prof.get("device_name_hint") or "").strip()
        if hint:
            mapping["TELBOT_INDI_DEVICE"] = hint
            mapping["TELBOT_INDI_DEVICE_AUTO"] = "true"
        pid = (prof.get("id") or "").strip()
        if pid:
            mapping["TELBOT_ACTIVE_MOUNT_PROFILE"] = pid

    collect_fn, _ = _load_indi_auto_connect()[:2]
    if collect_fn and args_line.strip():
        jobs = collect_fn(
            manifest_data,
            prof,
            args_line,
            vidpids,
            by_ids,
            profile_matches_fn=_profile_matches,
            optional_drivers_resolved_fn=_optional_indi_drivers_resolved,
        )
        reg = manifest_data.get("auto_connect_by_driver") or {}
        for drv, dev in jobs:
            entry = dict(reg.get(drv) or {})
            env_k = (entry.get("env") or entry.get("env_key") or "").strip()
            if env_k and dev:
                mapping[env_k] = dev
    return mapping


def _sync_dotenv(
    prof: dict,
    write_env: bool,
    *,
    manifest_data: dict | None = None,
    args_line: str = "",
    vidpids: set[str] | None = None,
    by_ids: list[str] | None = None,
) -> None:
    if not write_env:
        return
    manifest = manifest_data or {}
    mapping = _build_dotenv_mapping(
        prof,
        manifest,
        args_line,
        vidpids if vidpids is not None else set(),
        by_ids if by_ids is not None else [],
    )
    if not mapping:
        print("Skipping .env sync (no keys to write)", file=sys.stderr)
        return
    resolve_dotenv_path, update_dotenv_keys = _load_env_sync()
    env_path = resolve_dotenv_path()
    update_dotenv_keys(env_path, mapping)
    summary = ", ".join(f"{k}={v!r}" for k, v in sorted(mapping.items()))
    print(f"Updated {env_path} ({summary})", file=sys.stderr)


def _sync_dotenv_safe(
    prof: dict,
    write_env: bool,
    *,
    manifest_data: dict | None = None,
    args_line: str = "",
    vidpids: set[str] | None = None,
    by_ids: list[str] | None = None,
) -> None:
    try:
        _sync_dotenv(
            prof,
            write_env,
            manifest_data=manifest_data,
            args_line=args_line,
            vidpids=vidpids,
            by_ids=by_ids,
        )
    except ImportError as e:
        print(f"Warning: .env sync skipped ({e})", file=sys.stderr)
    except OSError as e:
        print(f"Warning: .env sync failed: {e}", file=sys.stderr)
    except ValueError as e:
        print(f"Warning: .env sync skipped ({e})", file=sys.stderr)


def _indi_port() -> int:
    try:
        return int(os.environ.get("TELBOT_INDI_PORT", "7624"))
    except ValueError:
        return 7624


def _free_indi_port(port: int) -> None:
    """Stop stray indiserver (manual ``indiserver -v … &``) so systemd owns 7624."""
    if subprocess.run(["which", "fuser"], capture_output=True).returncode == 0:
        subprocess.run(
            ["fuser", "-k", f"{port}/tcp"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    else:
        subprocess.run(["pkill", "-x", "indiserver"], capture_output=True, timeout=15)


def _systemctl_restart(unit: str) -> int:
    port = _indi_port()
    stop = subprocess.run(
        ["systemctl", "stop", unit],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if stop.returncode != 0 and "not loaded" not in (stop.stderr or "").lower():
        print(stop.stderr or stop.stdout or f"systemctl stop failed: {stop.returncode}", file=sys.stderr)
    _free_indi_port(port)
    start = subprocess.run(
        ["systemctl", "start", unit],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if start.returncode != 0:
        print(start.stderr or start.stdout or f"systemctl start failed: {start.returncode}", file=sys.stderr)
        return start.returncode
    subprocess.run(
        ["indi_getprop", "-p", str(port), "-t", "8", "*.*.*"],
        capture_output=True,
        text=True,
        timeout=12,
    )
    print(f"Restarted {unit} (logs: journalctl -u {unit} -f)", file=sys.stderr)
    return EXIT_OK


def _systemctl_stop(unit: str) -> int:
    r = subprocess.run(
        ["systemctl", "stop", unit],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r.returncode != 0:
        print(r.stderr or r.stdout or f"systemctl stop failed: {r.returncode}", file=sys.stderr)
        return r.returncode
    print(f"Stopped {unit}")
    return EXIT_OK


def _build_args_line_from_profile(prof: dict, vidpids: set[str], by_ids: list[str]) -> str | None:
    override = (prof.get("indiserver_args_line") or "").strip()
    if override:
        return override
    drivers = list(prof.get("indi_drivers") or [])
    opt = _optional_indi_drivers_resolved(prof, vidpids, by_ids)
    if not drivers:
        return None
    return "-v " + " ".join(drivers + opt)


def _apply_args_hint_restart(
    args_line: str,
    hint: str,
    pid: str,
    dotenv_prof: dict,
    *,
    unit: str,
    dry: bool,
    no_restart: bool,
    defer_restart: bool,
    write_env: bool,
    vidpids: set[str],
    by_ids: list[str],
    log_label: str,
) -> int:
    if dry:
        print(f"Would select {log_label} profile={pid!r} args={args_line!r} hint={hint!r}")
        print(f"lsusb VID:PID: {sorted(vidpids)}")
        print(f"by-id: {by_ids[:8]}{'...' if len(by_ids) > 8 else ''}")
        if _profile_requires_pwi4(dotenv_prof):
            print("Would require PWI4 (systemctl start pwi4.service, wait :8220)")
        else:
            print("Would stop PWI4 if running (no PlaneWave profile)")
        manifest_path = Path(
            os.environ.get("TELBOT_MOUNT_PROFILES", str(DEFAULT_MANIFEST))
        ).resolve()
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if write_env:
            preview = _build_dotenv_mapping(
                dotenv_prof, manifest_data, args_line, vidpids, by_ids
            )
            if preview:
                print(f"Would sync .env keys: {sorted(preview.keys())}")
            else:
                print("Would skip .env sync (no keys)")
        if not no_restart or defer_restart:
            print(f"Would restart {unit} (outside flock when invoked via telbot-select-mount.sh)")
        return EXIT_OK

    RUN.mkdir(parents=True, exist_ok=True)
    args_path = RUN / "indiserver.args"
    prev = args_path.read_text(encoding="utf-8") if args_path.is_file() else None
    new_text = args_line + "\n"
    hint_path = RUN / "indi_device_hint"
    prev_hint = hint_path.read_text(encoding="utf-8").strip() if hint_path.is_file() else ""

    manifest_path = Path(
        os.environ.get("TELBOT_MOUNT_PROFILES", str(DEFAULT_MANIFEST))
    ).resolve()
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))

    if prev == new_text and prev_hint == hint:
        if not no_restart:
            print("indiserver args unchanged; skip restart", file=sys.stderr)
        _sync_dotenv_safe(
            dotenv_prof,
            write_env,
            manifest_data=manifest_data,
            args_line=args_line,
            vidpids=vidpids,
            by_ids=by_ids,
        )
        if not dry:
            _save_auto_connect_plan_from_profile(
                manifest_data, dotenv_prof, args_line, vidpids, by_ids
            )
        return EXIT_OK

    args_path.write_text(new_text, encoding="utf-8")
    hint_path.write_text((hint + "\n") if hint else "", encoding="utf-8")
    (RUN / "mount_profile_id").write_text(pid + "\n", encoding="utf-8")
    _write_pwi4_required_flag(_profile_requires_pwi4(dotenv_prof))

    if not dry:
        _save_auto_connect_plan_from_profile(
            manifest_data, dotenv_prof, args_line, vidpids, by_ids
        )
    elif _load_indi_auto_connect()[0] is not None:
        collect_fn = _load_indi_auto_connect()[0]
        if collect_fn:
            jobs = collect_fn(
                manifest_data,
                dotenv_prof,
                args_line,
                vidpids,
                by_ids,
                profile_matches_fn=_profile_matches,
                optional_drivers_resolved_fn=_optional_indi_drivers_resolved,
            )
            if jobs:
                print(f"Would auto-connect: {jobs}", file=sys.stderr)

    if no_restart:
        _sync_dotenv_safe(
            dotenv_prof,
            write_env,
            manifest_data=manifest_data,
            args_line=args_line,
            vidpids=vidpids,
            by_ids=by_ids,
        )
        if defer_restart:
            print(f"Applied {log_label} profile {pid!r} (restart deferred to telbot-select-mount.sh)")
            return EXIT_RESTART_NEEDED
        print(f"Applied {log_label} profile {pid!r} (no systemctl restart; service start will pick up args)")
        return EXIT_OK

    rc = _systemctl_restart(unit)
    if rc != EXIT_OK:
        return rc
    print(f"Applied {log_label} profile {pid!r}, restarted {unit}")
    _sync_dotenv_safe(
        dotenv_prof,
        write_env,
        manifest_data=manifest_data,
        args_line=args_line,
        vidpids=vidpids,
        by_ids=by_ids,
    )
    _run_auto_connect_after_restart(
        manifest_data, dotenv_prof, args_line, vidpids, by_ids, dry=dry
    )
    return EXIT_OK


def _handle_no_usb_match(
    data: dict,
    vidpids: set[str],
    by_ids: list[str],
    *,
    unit: str,
    dry: bool,
    no_restart: bool,
    defer_restart: bool,
    write_env: bool,
) -> int:
    cfg = data.get("on_no_usb_match")
    if cfg is None:
        print(
            "No mount profile matches connected USB (lsusb VID:PID or /dev/serial/by-id).\n"
            f"  lsusb VID:PID: {sorted(vidpids) or '(none)'}\n"
            f"  by-id: {by_ids[:8]}{'...' if len(by_ids) > 8 else ''}\n"
            "Set top-level on_no_usb_match in mount_profiles.json (see docs/MOUNT_AUTO.md) "
            "or plug in a supported mount.",
            file=sys.stderr,
        )
        return EXIT_ERROR

    action = (cfg.get("action") or "restart").strip().lower()
    if action == "exit_error":
        print(
            "No mount profile matches connected USB (lsusb VID:PID or /dev/serial/by-id).\n"
            f"  lsusb VID:PID: {sorted(vidpids) or '(none)'}\n"
            f"  by-id: {by_ids[:8]}{'...' if len(by_ids) > 8 else ''}\n"
            "on_no_usb_match.action is exit_error; plug in a supported mount or change the manifest.",
            file=sys.stderr,
        )
        return EXIT_ERROR

    if action == "stop":
        if _env_flag("TELBOT_SELECT_MOUNT_TRY_LOCK"):
            print(
                "on_no_usb_match action stop is not used under ExecStartPre (TRY_LOCK); "
                "using restart fallback instead.",
                file=sys.stderr,
            )
            action = "restart"
        else:
            if dry:
                print(f"Would systemctl stop {unit} (no USB match)")
                return EXIT_OK
            rc = _systemctl_stop(unit)
            if rc != EXIT_OK:
                return rc
            line = (cfg.get("indiserver_args_line") or "").strip()
            if line:
                RUN.mkdir(parents=True, exist_ok=True)
                (RUN / "indiserver.args").write_text(line + "\n", encoding="utf-8")
                hint = (cfg.get("device_name_hint") or "").strip()
                pid = (cfg.get("mount_profile_id") or "no_usb_match").strip()
                (RUN / "indi_device_hint").write_text((hint + "\n") if hint else "", encoding="utf-8")
                (RUN / "mount_profile_id").write_text(pid + "\n", encoding="utf-8")
            _sync_dotenv_safe(
                {
                    "id": (cfg.get("mount_profile_id") or "no_usb_match").strip(),
                    "device_name_hint": (cfg.get("device_name_hint") or "").strip(),
                    "telbot_env_sync": cfg.get("telbot_env_sync", False),
                },
                write_env,
            )
            return EXIT_OK

    if action != "restart":
        print(f"Invalid on_no_usb_match.action: {action!r}", file=sys.stderr)
        return EXIT_ERROR

    args_line = (cfg.get("indiserver_args_line") or "").strip()
    if not args_line:
        print("on_no_usb_match requires indiserver_args_line when action is restart", file=sys.stderr)
        return EXIT_ERROR
    hint = (cfg.get("device_name_hint") or "").strip()
    pid = (cfg.get("mount_profile_id") or "no_usb_match").strip()
    eff = {
        "id": pid,
        "device_name_hint": hint,
        "telbot_env_sync": cfg.get("telbot_env_sync", False),
        "requires_pwi4": False,
    }
    _write_pwi4_required_flag(False)
    print(
        "No mount profile matches connected USB; applying on_no_usb_match fallback.\n"
        f"  lsusb VID:PID: {sorted(vidpids) or '(none)'}\n"
        f"  by-id: {by_ids[:8]}{'...' if len(by_ids) > 8 else ''}",
        file=sys.stderr,
    )
    return _apply_args_hint_restart(
        args_line,
        hint,
        pid,
        eff,
        unit=unit,
        dry=dry,
        no_restart=no_restart,
        defer_restart=defer_restart,
        write_env=write_env,
        vidpids=vidpids,
        by_ids=by_ids,
        log_label="on_no_usb_match",
    )


def _post_restart_auto_connect_main() -> int:
    """Run CONNECTION.CONNECT from /run/telbot/auto_connect.json (after shell systemctl restart)."""
    if not _auto_connect_enabled():
        return EXIT_OK
    plan_path = RUN / "auto_connect.json"
    if not plan_path.is_file():
        return EXIT_OK
    collect_fn, run_fn, mod = _load_indi_auto_connect()
    if collect_fn is None or run_fn is None:
        print(
            "Error: indi_auto_connect not available "
            f"(expected {SCRIPT_DIR / 'indi_auto_connect_lite.py'})",
            file=sys.stderr,
        )
        return EXIT_ERROR
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    host = str(payload.get("host") or "127.0.0.1")
    port = int(payload.get("port") or 7624)
    raw_jobs = payload.get("jobs") or []
    jobs = [(str(a), str(b)) for a, b in raw_jobs]
    if not jobs:
        return EXIT_OK
    if _env_flag("TELBOT_SELECT_MOUNT_DRY_RUN"):
        run_fn(jobs, host, port, dry_run=True)
        return EXIT_OK
    print(f"Post-restart auto-connect {len(jobs)} device(s)…", file=sys.stderr)
    pre = [str(x) for x in (payload.get("pre_connect_setprop") or []) if str(x).strip()]
    if not pre and mod is not None and hasattr(mod, "collect_pre_connect_setprops"):
        plan_path_manifest = Path(
            os.environ.get("TELBOT_MOUNT_PROFILES", str(DEFAULT_MANIFEST))
        ).resolve()
        if plan_path_manifest.is_file():
            manifest_data = json.loads(plan_path_manifest.read_text(encoding="utf-8"))
            pre = mod.collect_pre_connect_setprops(manifest_data, jobs)
    results = run_fn(jobs, host, port, dry_run=False, pre_connect_setprop=pre or None)
    failed = False
    for drv, dev, r in results:
        if r.returncode != 0:
            failed = True
            print(
                f"Warning: auto-connect {dev!r} ({drv}) failed: {r.stderr or r.stdout}",
                file=sys.stderr,
            )
        else:
            print(f"Auto-connected {dev!r} ({drv})", file=sys.stderr)
    return EXIT_ERROR if failed else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Select INDI mount profile from USB")
    parser.add_argument(
        "--no-write-env",
        action="store_true",
        help="Do not update .env after a successful profile apply",
    )
    parser.add_argument(
        "--post-restart-auto-connect",
        action="store_true",
        help="Run auto CONNECT from /run/telbot/auto_connect.json (internal; telbot-select-mount.sh)",
    )
    args = parser.parse_args(argv)

    if args.post_restart_auto_connect:
        return _post_restart_auto_connect_main()

    dry = _env_flag("TELBOT_SELECT_MOUNT_DRY_RUN")
    no_restart = _env_flag("TELBOT_SELECT_MOUNT_NO_RESTART")
    defer_restart = _env_flag("TELBOT_SELECT_MOUNT_DEFER_RESTART")
    write_env = os.environ.get("TELBOT_SELECT_MOUNT_WRITE_ENV", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )
    write_env = write_env and not args.no_write_env

    manifest = Path(os.environ.get("TELBOT_MOUNT_PROFILES", str(DEFAULT_MANIFEST))).resolve()
    unit = os.environ.get("TELBOT_INDI_SYSTEMD_UNIT", "indi-telescope.service").strip()

    if not manifest.is_file():
        print(f"Manifest not found: {manifest}", file=sys.stderr)
        return EXIT_ERROR

    data = json.loads(manifest.read_text(encoding="utf-8"))
    vidpids = _apply_udev_removed_vidpids(_lsusb_vid_pids())
    by_ids = _by_id_strings()
    prof = select_profile(data, vidpids, by_ids)
    if prof is None:
        return _handle_no_usb_match(
            data,
            vidpids,
            by_ids,
            unit=unit,
            dry=dry,
            no_restart=no_restart,
            defer_restart=defer_restart,
            write_env=write_env,
        )

    args_line = _build_args_line_from_profile(prof, vidpids, by_ids)
    if args_line is None:
        print("Profile has empty indi_drivers", file=sys.stderr)
        return EXIT_ERROR
    hint = (prof.get("device_name_hint") or "").strip()
    pid = (prof.get("id") or "").strip()

    return _apply_args_hint_restart(
        args_line,
        hint,
        pid,
        prof,
        unit=unit,
        dry=dry,
        no_restart=no_restart,
        defer_restart=defer_restart,
        write_env=write_env,
        vidpids=vidpids,
        by_ids=by_ids,
        log_label="USB",
    )


if __name__ == "__main__":
    raise SystemExit(main())
