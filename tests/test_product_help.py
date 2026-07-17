"""Product help / capabilities intent."""

from telbot.intent_nl import build_intent_nl
from telbot.intent_exec import execute_voice_intent
from telbot.models import VoiceIntentV1
from telbot.product_help import build_product_help


def test_build_product_help() -> None:
    out = build_product_help()
    assert out["action"] == "help"
    assert out["ok"] is True
    lines = out["summary_lines"]
    assert any("Telbot" in ln for ln in lines)
    assert any("赤道仪" in ln for ln in lines)
    assert len(out["supported_devices"]) >= 5


def test_help_nl() -> None:
    raw = build_product_help()
    nl = build_intent_nl(raw)
    assert "Telbot" in nl["text"]
    assert "语音" in nl["text"] or "说" in nl["text"]


def test_execute_help_attaches_nl() -> None:
    from telbot.config import Settings

    s = Settings()
    out = execute_voice_intent(s, VoiceIntentV1(version=1, action="help"), execute=False)
    assert out["action"] == "help"
    assert "nl" in out
    assert "功能" in out["nl"]["text"] or "Telbot" in out["nl"]["text"]
