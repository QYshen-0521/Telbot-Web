"""Mount pointing verification (dry-run and mocked execute)."""

from __future__ import annotations

from telbot.config import Settings
from telbot.mount_verify import verify_mount_pointing


def test_verify_pointing_dry_run() -> None:
    out = verify_mount_pointing(Settings(), execute=False, align="sync")
    assert out["ok"]
    assert out["dry_run"]
    assert out["align"] == "sync"
    assert "plate solve" in out["message"]


def test_verify_pointing_mock_execute() -> None:
    def fake_exec(_s: object, intent: object, *, execute: bool) -> dict:
        assert execute
        assert getattr(intent, "action") == "platesolve"
        return {
            "ok": True,
            "platesolve": {"ra_hours": 1.5, "dec_deg": 10.0},
            "align": {"ok": True},
        }

    out = verify_mount_pointing(
        Settings(),
        execute=True,
        exposure_seconds=3.0,
        align="sync",
        intent_exec_fn=fake_exec,
    )
    assert out["ok"]
    assert out["center_ra_hours"] == 1.5
    assert out["center_dec_deg"] == 10.0


def test_verify_pointing_failed_solve() -> None:
    def fake_fail(_s: object, _intent: object, *, execute: bool) -> dict:
        return {"ok": False, "platesolve": {}}

    out = verify_mount_pointing(Settings(), execute=True, intent_exec_fn=fake_fail)
    assert not out["ok"]
