"""Scheduling utilities: time, abort, confirmation."""

from __future__ import annotations

import datetime as dt
import threading

import pytest

from telbot.scheduling.abort import AbortController, AbortRequested
from telbot.scheduling.confirmation import apply_plan_confirmation, validate_plan_confirmation
from telbot.scheduling.time_util import parse_utc_iso, seconds_until, wait_until_utc


def test_parse_utc_iso_z_and_offset() -> None:
    d = parse_utc_iso("2026-05-30T12:00:00Z")
    assert d.tzinfo == dt.timezone.utc
    assert d.hour == 12
    d2 = parse_utc_iso("2026-05-30T20:00:00+08:00")
    assert d2.hour == 12


def test_parse_utc_iso_requires_timezone() -> None:
    with pytest.raises(ValueError, match="时区"):
        parse_utc_iso("2026-05-30T12:00:00")


def test_wait_until_utc_returns_when_past(monkeypatch: pytest.MonkeyPatch) -> None:
    target = dt.datetime(2026, 5, 30, 12, 0, tzinfo=dt.timezone.utc)
    monkeypatch.setattr(
        "telbot.scheduling.time_util.utc_now",
        lambda: target + dt.timedelta(seconds=1),
    )
    wait_until_utc(target, poll_seconds=0.01)


def test_wait_until_utc_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    start = dt.datetime(2026, 5, 30, 12, 0, tzinfo=dt.timezone.utc)
    target = start + dt.timedelta(seconds=2)
    ticks: list[float] = []

    def fake_now() -> dt.datetime:
        if not ticks:
            return start
        return target

    monkeypatch.setattr("telbot.scheduling.time_util.utc_now", fake_now)
    monkeypatch.setattr("telbot.scheduling.time_util.time.sleep", lambda _s: None)
    wait_until_utc(target, poll_seconds=0.01, on_tick=ticks.append)
    assert ticks
    assert ticks[0] > 0


def test_abort_controller_check() -> None:
    ctrl = AbortController()
    ctrl.request("test stop")
    with pytest.raises(AbortRequested, match="test stop"):
        ctrl.check()


def test_abort_controller_flag_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    flag = tmp_path / "abort.flag"
    ctrl = AbortController(flag_path=flag)
    ctrl.check()  # no flag yet → no abort
    flag.write_text("stop now", encoding="utf-8")
    with pytest.raises(AbortRequested, match="stop now"):
        ctrl.check()
    assert ctrl.aborted


def test_abort_controller_on_abort_fires_once(tmp_path) -> None:  # type: ignore[no-untyped-def]
    flag = tmp_path / "abort.flag"
    calls: list[str] = []
    ctrl = AbortController(flag_path=flag, on_abort=lambda reason: calls.append(reason))
    flag.write_text("emergency", encoding="utf-8")
    with pytest.raises(AbortRequested):
        ctrl.check()
    # repeated checks must not re-fire on_abort
    with pytest.raises(AbortRequested):
        ctrl.check()
    assert calls == ["emergency"]
    assert ctrl.on_abort_fired


def test_abort_controller_watch_thread_fires(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import time

    flag = tmp_path / "abort.flag"
    fired = threading.Event()
    ctrl = AbortController(
        flag_path=flag,
        on_abort=lambda _reason: fired.set(),
        poll_interval=0.05,
    )
    with ctrl:
        flag.write_text("from other process", encoding="utf-8")
        assert fired.wait(timeout=2.0), "watcher 应在标志出现后触发 on_abort"
    assert ctrl.aborted


def test_apply_and_validate_confirmation() -> None:
    payload: dict = {"schema_version": "telbot.plan_tonight.v1", "confirmation": None}
    apply_plan_confirmation(payload, via="unit")
    assert payload["confirmation"]["via"] == "unit"
    validate_plan_confirmation(
        payload,
        expected_schema_prefix="telbot.plan_tonight",
        will_execute=True,
    )


def test_validate_skips_dry_run() -> None:
    validate_plan_confirmation(
        {"schema_version": "telbot.plan_tonight.v1"},
        expected_schema_prefix="telbot.plan_tonight",
        will_execute=False,
    )


def test_validate_requires_confirmation_on_execute() -> None:
    with pytest.raises(ValueError, match="confirmation"):
        validate_plan_confirmation(
            {"schema_version": "telbot.plan_tonight.v1"},
            expected_schema_prefix="telbot.plan_tonight",
            will_execute=True,
        )


def test_seconds_until_future() -> None:
    future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    assert seconds_until(future) > 3500
