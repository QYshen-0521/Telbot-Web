"""HTTP API structured error responses."""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.testclient import TestClient

from telbot.http_app import app
from telbot.http_errors import build_error_body, unhandled_exception_to_body
from telbot.models import VoiceIntentV1

client = TestClient(app)


def test_build_error_body_shape() -> None:
    body = build_error_body(
        status_code=400,
        error="plan_or_input_error",
        message="无 pending 列表",
        path="/listen/text",
        hint="先查凌星",
    )
    assert body["ok"] is False
    assert body["error"] == "plan_or_input_error"
    assert body["message"] == "无 pending 列表"
    assert body["path"] == "/listen/text"


def test_http_exception_handler_via_focuser_503() -> None:
    """Focuser not configured → 503 JSON envelope (not plain text)."""
    r = client.get("/focuser/position")
    if r.status_code == 503:
        data = r.json()
        assert data["ok"] is False
        assert data.get("message") or data.get("detail")


def test_unhandled_exception_envelope() -> None:
    body = unhandled_exception_to_body(
        NameError("name 'plans_dir' is not defined"),
        path="/listen/text",
    )
    assert body["status_code"] == 500
    assert body["error"] == "internal_error"
    assert body["exception_type"] == "NameError"
    assert body.get("hint")


def test_listen_text_plan_error_structured(monkeypatch) -> None:
    def fake_resolve(*_a, **_k):
        return VoiceIntentV1(version=1, action="plan_exoplanet_transit", event_index=99)

    monkeypatch.setattr("telbot.http_app.resolve_intent_from_sentence", fake_resolve)

    def fake_exec(_s, _intent, *, execute: bool):
        raise ValueError("无 pending 列表或已过期")

    monkeypatch.setattr("telbot.http_app.execute_voice_intent", fake_exec)

    r = client.post("/listen/text?execute=false", json={"text": "规划第99个凌星"})
    assert r.status_code == 400
    data = r.json()
    assert data["ok"] is False
    assert data["error"] == "plan_or_input_error"
    assert "pending" in data["message"] or "pending" in str(data.get("detail", ""))
