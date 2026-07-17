"""Phase 4: validation and dry-run execute without INDI."""

from __future__ import annotations

import json

import pytest

from telbot.config import Settings
from telbot.planning.execute import (
    execute_tonight_plan,
    validate_plan_for_execution,
)


def test_validate_requires_confirmation_when_execute() -> None:
    with pytest.raises(ValueError, match="confirmation"):
        validate_plan_for_execution(
            {"schema_version": "telbot.plan_tonight.v1"},
            will_execute=True,
            force=False,
        )


def test_validate_allows_dry_run_without_confirmation() -> None:
    validate_plan_for_execution(
        {"schema_version": "telbot.plan_tonight.v1"},
        will_execute=False,
        force=False,
    )


def test_execute_dry_run_minimal_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_goto(s, target, *, dry_run: bool):
        return {"ok": True, "resolved": {"ra_hours": 1.0, "dec_deg": 0.0, "label": "x"}, "device": "T", "steps": []}

    monkeypatch.setattr("telbot.planning.execute._goto_from_j2000", fake_goto)

    payload = {
        "schema_version": "telbot.plan_tonight.v1",
        "confirmation": {"via": "test"},
        "targets": [
            {
                "catalog_id": "M1",
                "label": "M1",
                "ra_j2000_deg": 83.0,
                "dec_j2000_deg": 22.0,
            }
        ],
        "schedule": {
            "blocks": [{"order": 1, "target_id": "M1", "start_utc": "", "end_utc": ""}],
        },
    }
    out = execute_tonight_plan(
        Settings(),
        payload,
        execute=False,
        snap_after_goto=False,
        on_failure="abort",
        force=True,
    )
    assert out["ok"]
    assert out["dry_run"]
    assert out["blocks_executed"] == 1
