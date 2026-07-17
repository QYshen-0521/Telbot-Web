"""Phase 3: tonight payload wraps phase 2 schema."""

from __future__ import annotations

from telbot.config import Settings
from telbot.planning.tonight import apply_confirmation, build_tonight_payload


def test_build_tonight_payload_schema(monkeypatch) -> None:
    def fake_phase2(*a: object, **k: object) -> dict:
        return {
            "schema_version": "telbot.plan_phase2.v1",
            "generated_at_utc": "2026-01-01T00:00:00+00:00",
            "schedule": {"blocks": []},
            "targets": [],
        }

    monkeypatch.setattr(
        "telbot.planning.tonight.build_phase2_payload",
        fake_phase2,
    )
    out = build_tonight_payload(Settings(), None, None, include_weather=False)
    assert out["schema_version"] == "telbot.plan_tonight.v1"
    assert out["phase2_schema_version"] == "telbot.plan_phase2.v1"
    assert out["confirmation"] is None


def test_apply_confirmation() -> None:
    p: dict = {"schema_version": "telbot.plan_tonight.v1", "confirmation": None}
    apply_confirmation(p, via="test")
    assert p["confirmation"]["via"] == "test"
    assert "confirmed_at_utc" in p["confirmation"]
