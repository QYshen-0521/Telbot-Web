from telbot.indi import IndiResult, abort_motion, slew_equatorial_eod, sync_equatorial_eod


def test_slew_dry_run_no_subprocess_crash() -> None:
    r1, r2 = slew_equatorial_eod(
        "Test Mount",
        "127.0.0.1",
        7624,
        1.0,
        2.0,
        dry_run=True,
    )
    assert r1.returncode == 0
    assert "dry-run" in r1.stdout.lower()
    assert r2.returncode == 0


def test_sync_dry_run_no_subprocess_crash() -> None:
    r1, r2 = sync_equatorial_eod(
        "Test Mount",
        "127.0.0.1",
        7624,
        1.0,
        2.0,
        dry_run=True,
    )
    assert r1.returncode == 0
    assert "dry-run" in r1.stdout.lower()
    assert r2.returncode == 0
    assert "SYNC" in r2.stdout


def test_abort_motion_no_setprop_when_abort_switch_missing(monkeypatch) -> None:
    setprop_calls: list[int] = []

    def fake_getprop(host, port, pattern, timeout=10.0):
        _ = (host, port, timeout)
        if "TELESCOPE_ABORT_MOTION" in pattern:
            return IndiResult(0, "", "")
        if "CONNECTION.CONNECT" in pattern:
            return IndiResult(0, "Celestron GPS.CONNECTION.CONNECT=Off\n", "")
        return IndiResult(0, "", "")

    def fake_setprop(*_a, **_k):
        setprop_calls.append(1)
        return IndiResult(0, "", "")

    monkeypatch.setattr("telbot.indi.run_getprop", fake_getprop)
    monkeypatch.setattr("telbot.indi.run_setprop", fake_setprop)
    r = abort_motion("Celestron GPS", "127.0.0.1", 7624, dry_run=False)
    assert r.returncode == 1
    assert not setprop_calls
    assert "CONNECT" in r.stderr
    assert "mount connect" in r.stderr


def test_abort_motion_calls_setprop_when_abort_visible(monkeypatch) -> None:
    setprop_calls: list[int] = []

    def fake_getprop(host, port, pattern, timeout=10.0):
        _ = (host, port, timeout)
        if "TELESCOPE_ABORT_MOTION" in pattern:
            return IndiResult(0, "Celestron GPS.TELESCOPE_ABORT_MOTION.ABORT=Off\n", "")
        return IndiResult(0, "", "")

    def fake_setprop(*_a, **_k):
        setprop_calls.append(1)
        return IndiResult(0, "ok", "")

    monkeypatch.setattr("telbot.indi.run_getprop", fake_getprop)
    monkeypatch.setattr("telbot.indi.run_setprop", fake_setprop)
    r = abort_motion("Celestron GPS", "127.0.0.1", 7624, dry_run=False)
    assert r.returncode == 0
    assert setprop_calls == [1]
