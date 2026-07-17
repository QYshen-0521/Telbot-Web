"""Transit plan timed execution (mocked)."""

from __future__ import annotations

import datetime as dt

import pytest

from telbot.config import Settings
from telbot.planning.transit_execute import execute_transit_plan
from telbot.scheduling.confirmation import apply_plan_confirmation


def _minimal_plan() -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "schema_version": "telbot.plan_transit.v1",
        "confirmation": None,
        "steps": [
            {
                "kind": "absolute",
                "at_utc": (now - dt.timedelta(seconds=1)).isoformat(),
                "action": "mount_connect",
            },
            {
                "kind": "interval",
                "from_utc": now.isoformat(),
                "until_utc": (now + dt.timedelta(seconds=0.01)).isoformat(),
                "action": "expose_loop",
                "exposure_seconds": 1.0,
                "cadence_seconds": 0.01,
                "session_tag": "test",
            },
        ],
    }
    apply_plan_confirmation(payload, via="test")
    return payload


def test_execute_transit_dry_run() -> None:
    calls: list[str] = []

    def fake_exec(_s: object, intent: object, *, execute: bool) -> dict:
        calls.append(getattr(intent, "action", "?"))
        return {"ok": True, "dry_run": not execute}

    out = execute_transit_plan(
        Settings(),
        _minimal_plan(),
        execute=False,
        force=True,
        skip_wait=True,
        intent_exec_fn=fake_exec,
    )
    assert out["ok"]
    assert out["dry_run"]
    assert "connect" in calls


def test_execute_requires_confirmation() -> None:
    plan = _minimal_plan()
    plan["confirmation"] = None
    with pytest.raises(ValueError, match="confirmation"):
        execute_transit_plan(Settings(), plan, execute=True, force=False, skip_wait=True)


def test_abort_flag_triggers_emergency_mount_stop(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """A pre-set abort flag must immediately fire a mount abort and stop the run."""
    flag = tmp_path / "transit_abort.flag"
    monkeypatch.setattr(
        "telbot.planning.transit_execute.transit_abort_flag_path", lambda: flag
    )
    monkeypatch.setattr(
        "telbot.planning.transit_execute.clear_abort_flag", lambda: None
    )
    flag.write_text("user requested abort", encoding="utf-8")

    calls: list[str] = []

    def fake_exec(_s: object, intent: object, *, execute: bool) -> dict:
        calls.append(getattr(intent, "action", "?"))
        return {"ok": True, "dry_run": not execute}

    out = execute_transit_plan(
        Settings(),
        _minimal_plan(),
        execute=True,
        force=True,
        skip_wait=True,
        intent_exec_fn=fake_exec,
    )

    # The mount-abort emergency stop must have been dispatched.
    assert "abort" in calls
    assert out["stopped_reason"] and out["stopped_reason"].startswith("aborted")
    assert any(r.get("action") == "emergency_mount_abort" for r in out["results"])
    assert not out["ok"]
