"""Execute telbot.plan_transit.v1 on a UTC timeline."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from telbot.config import Settings
from telbot.expose_loop import run_expose_loop
from telbot.models import VoiceIntentV1
from telbot.mount_verify import verify_mount_pointing
from telbot.planning.execute import load_plan_json
from telbot.planning.transit_abort import clear_abort_flag
from telbot.planning.transit_ingress_precheck import run_ingress_precheck
from telbot.planning.transit_plan import SCHEMA_VERSION, resolve_latest_transit_plan
from telbot.repo_paths import transit_abort_flag_path
from telbot.scheduling.abort import AbortController, AbortRequested
from telbot.scheduling.confirmation import validate_plan_confirmation
from telbot.scheduling.time_util import parse_utc_iso, wait_until_utc

OnFailureMode = Literal["abort", "continue", "park"]


def validate_transit_plan_for_execution(
    payload: dict[str, Any],
    *,
    will_execute: bool,
    force: bool = False,
) -> None:
    validate_plan_confirmation(
        payload,
        expected_schema_prefix="telbot.plan_transit",
        will_execute=will_execute,
        force=force,
    )


def _parse_step_time(step: dict[str, Any], key: str) -> dt.datetime:
    return parse_utc_iso(str(step[key]))


def _dispatch_absolute_step(
    s: Settings,
    step: dict[str, Any],
    *,
    execute: bool,
    intent_exec_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    action = str(step.get("action", ""))
    if action == "mount_connect":
        return intent_exec_fn(s, VoiceIntentV1(version=1, action="connect"), execute=execute)
    if action == "mount_unpark":
        return intent_exec_fn(s, VoiceIntentV1(version=1, action="unpark"), execute=execute)
    if action == "mount_park":
        return intent_exec_fn(s, VoiceIntentV1(version=1, action="park"), execute=execute)
    if action == "mount_abort":
        return intent_exec_fn(s, VoiceIntentV1(version=1, action="abort"), execute=execute)
    if action == "mount_goto":
        return intent_exec_fn(
            s,
            VoiceIntentV1(
                version=1,
                action="goto",
                ra_hours=float(step["ra_hours"]),
                dec_deg=float(step["dec_deg"]),
                frame="JNOW",
            ),
            execute=execute,
        )
    if action == "camera_snap":
        exp = step.get("exposure_seconds")
        return intent_exec_fn(
            s,
            VoiceIntentV1(
                version=1,
                action="snap",
                exposure_seconds=float(exp) if exp is not None else None,
            ),
            execute=execute,
        )
    if action == "cfw_goto":
        slot = step.get("slot_name") or step.get("filter") or ""
        return intent_exec_fn(
            s,
            VoiceIntentV1(version=1, action="cfw_goto", target=str(slot)),
            execute=execute,
        )
    if action in ("focuser_autofocus", "autofocus"):
        exp = step.get("exposure_seconds")
        return intent_exec_fn(
            s,
            VoiceIntentV1(
                version=1,
                action="focuser_autofocus",
                exposure_seconds=float(exp) if exp is not None else None,
            ),
            execute=execute,
        )
    if action == "platesolve_check":
        exp = step.get("exposure_seconds")
        return verify_mount_pointing(
            s,
            execute=execute,
            exposure_seconds=float(exp) if exp is not None else None,
            intent_exec_fn=intent_exec_fn,
        )
    if action == "ingress_precheck":
        return run_ingress_precheck(s, step, execute=execute, intent_exec_fn=intent_exec_fn)
    raise ValueError(f"未知计划步骤 action：{action!r}")


def _run_interval_step(
    s: Settings,
    step: dict[str, Any],
    *,
    execute: bool,
    abort: AbortController,
    on_fail: OnFailureMode,
) -> dict[str, Any]:
    if str(step.get("action")) != "expose_loop":
        raise ValueError(f"interval 步骤仅支持 expose_loop，当前为 {step.get('action')!r}")
    until = _parse_step_time(step, "until_utc")
    from_utc = _parse_step_time(step, "from_utc")
    now = dt.datetime.now(dt.timezone.utc)
    if execute and until <= now:
        return {
            "ok": False,
            "action": "expose_loop",
            "error": "expose_loop until_utc 已过期",
        }
    if execute and from_utc > now:
        wait_until_utc(from_utc, abort_check=abort.check)

    return run_expose_loop(
        s,
        until_utc=until,
        exposure_seconds=float(step.get("exposure_seconds") or s.plan_default_exposure_seconds),
        cadence_seconds=float(step.get("cadence_seconds") or 0) or None,
        session_tag=str(step.get("session_tag") or "") or None,
        execute=execute,
        abort=abort,
    )


def execute_transit_plan(
    s: Settings,
    payload: dict[str, Any],
    *,
    execute: bool,
    force: bool = False,
    on_fail: OnFailureMode = "abort",
    abort: AbortController | None = None,
    intent_exec_fn: Callable[..., dict[str, Any]] | None = None,
    skip_wait: bool = False,
) -> dict[str, Any]:
    """
    Run transit plan steps in order: wait until each absolute ``at_utc``, then dispatch.

    ``skip_wait``：干跑或测试时跳过阻塞等待。
    """
    validate_transit_plan_for_execution(payload, will_execute=execute, force=force)
    if intent_exec_fn is None:
        from telbot.intent_exec import execute_voice_intent

        intent_exec_fn = execute_voice_intent

    dry_run = not execute
    steps = list(payload.get("steps") or [])
    owns_controller = abort is None
    controller = abort or AbortController()
    results: list[dict[str, Any]] = []
    stopped_reason: str | None = None

    def _emergency_mount_stop(_reason: str) -> dict[str, Any]:
        """Halt the mount immediately on abort (TELESCOPE_ABORT_MOTION)."""
        return intent_exec_fn(s, VoiceIntentV1(version=1, action="abort"), execute=True)

    if execute:
        # Watch the out-of-band abort flag and arm the emergency mount stop so a
        # `telbot plan transit-abort` (or Ctrl+C / SIGTERM) stops all motion at once.
        controller.set_flag_path(transit_abort_flag_path())
        if not controller.has_on_abort:
            controller.set_on_abort(_emergency_mount_stop)
        if owns_controller:
            clear_abort_flag()

    def _fail(kind: str, step_idx: int, out: dict[str, Any]) -> bool:
        nonlocal stopped_reason
        results.append({"index": step_idx, "step": steps[step_idx - 1], "result": out})
        if on_fail == "abort":
            stopped_reason = kind
            return True
        if on_fail == "park":
            try:
                park_out = intent_exec_fn(
                    s, VoiceIntentV1(version=1, action="park"), execute=execute
                )
                results.append({"index": step_idx, "action": "on_failure_park", "result": park_out})
            except Exception as e:
                results.append({"index": step_idx, "action": "on_failure_park", "error": str(e)})
            stopped_reason = "park_after_failure"
            return True
        return False

    try:
        with controller:
            for idx, step in enumerate(steps, 1):
                controller.check()
                kind = str(step.get("kind", "absolute"))

                if kind == "absolute":
                    at = _parse_step_time(step, "at_utc")
                    if execute and not skip_wait:
                        now = dt.datetime.now(dt.timezone.utc)
                        if at > now:
                            wait_until_utc(at, abort_check=controller.check)
                    elif dry_run and not skip_wait:
                        remaining = (at - dt.datetime.now(dt.timezone.utc)).total_seconds()
                        if remaining > 0 and remaining > 86400:
                            results.append(
                                {
                                    "index": idx,
                                    "step": step,
                                    "skipped_wait": True,
                                    "wait_seconds": remaining,
                                    "dry_run": True,
                                }
                            )
                            continue

                    out = _dispatch_absolute_step(
                        s, step, execute=execute, intent_exec_fn=intent_exec_fn
                    )
                    results.append({"index": idx, "step": step, "result": out})
                    action = str(step.get("action", ""))
                    if action == "ingress_precheck":
                        if out.get("user_alert"):
                            results.append(
                                {
                                    "index": idx,
                                    "ingress_precheck_alert": out["user_alert"],
                                }
                            )
                        if not out.get("capture_ok", True) and execute:
                            policy = (
                                str(s.transit_ingress_precheck_fail_policy or "continue")
                                .strip()
                                .lower()
                            )
                            if policy == "abort":
                                if _fail("ingress_precheck_failed", idx, out):
                                    break
                            else:
                                out = {
                                    **out,
                                    "ok": True,
                                    "continued_after_precheck_failure": True,
                                }
                                results[-1]["result"] = out
                            continue
                    if not out.get("ok", False):
                        if _fail("step_failed", idx, out):
                            break
                    continue

                if kind == "interval":
                    out = _run_interval_step(
                        s,
                        step,
                        execute=execute,
                        abort=controller,
                        on_fail=on_fail,
                    )
                    results.append({"index": idx, "step": step, "result": out})
                    if not out.get("ok", False) and not out.get("aborted"):
                        if _fail("expose_loop_failed", idx, out):
                            break
                    continue

                results.append(
                    {
                        "index": idx,
                        "step": step,
                        "result": {"ok": False, "error": f"未知 kind {kind!r}"},
                    }
                )
                if _fail("unknown_kind", idx, results[-1]["result"]):
                    break

    except AbortRequested as e:
        stopped_reason = f"aborted:{e.reason}"
    except KeyboardInterrupt:
        stopped_reason = "keyboard_interrupt"
    finally:
        if execute and owns_controller:
            clear_abort_flag()

    aborted = stopped_reason is not None and (
        stopped_reason.startswith("aborted") or stopped_reason == "keyboard_interrupt"
    )
    if controller.on_abort_fired:
        results.append(
            {"action": "emergency_mount_abort", "result": controller.on_abort_result}
        )
    elif execute and aborted:
        # Fallback: ensure the mount is halted even if the watcher never fired.
        try:
            stop_out = intent_exec_fn(
                s, VoiceIntentV1(version=1, action="abort"), execute=True
            )
            results.append({"action": "emergency_mount_abort", "result": stop_out})
        except Exception as e:  # best-effort emergency stop
            results.append({"action": "emergency_mount_abort", "error": str(e)})

    step_rows = [r for r in results if r.get("step")]
    overall_ok = stopped_reason is None and bool(step_rows) and all(
        (r.get("result") or {}).get("ok") is not False or (r.get("result") or {}).get("aborted")
        for r in step_rows
    )

    from telbot.planning.transit_ingress_precheck import get_last_ingress_precheck

    ingress_precheck = get_last_ingress_precheck()

    return {
        "ok": overall_ok,
        "dry_run": dry_run,
        "schema_version": payload.get("schema_version", SCHEMA_VERSION),
        "stopped_reason": stopped_reason,
        "steps_executed": len(step_rows),
        "ingress_precheck": ingress_precheck,
        "results": results,
    }


def load_transit_plan(path: Path | None = None) -> dict[str, Any]:
    p = path if path is not None else resolve_latest_transit_plan()
    data = load_plan_json(p)
    sv = str(data.get("schema_version") or "")
    if not sv.startswith("telbot.plan_transit"):
        raise ValueError(f"不是凌星计划 schema：{sv!r}")
    return data
