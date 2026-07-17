"""Natural-language summaries for voice intent results."""

from telbot.intent_nl import attach_intent_nl, build_intent_nl


def test_usb_devices_empty_nl() -> None:
    raw = {
        "ok": True,
        "dry_run": True,
        "action": "usb_devices",
        "devices": [],
        "count": 0,
        "message": "当前没有识别到已登记的天文 USB 设备。",
    }
    nl = build_intent_nl(raw)
    assert nl["version"] == 1
    assert "没有" in nl["text"]
    assert nl["lines"] == [nl["text"]]


def test_attach_intent_nl_sibling() -> None:
    raw = {"ok": True, "action": "abort", "device": "Gemini", "dry_run": False}
    merged = attach_intent_nl(raw)
    assert merged["device"] == "Gemini"
    assert "nl" in merged
    assert "中止" in merged["nl"]["text"]


def test_goto_dry_run() -> None:
    raw = {
        "ok": True,
        "dry_run": True,
        "action": "goto",
        "mode": "body",
        "resolved": {"label": "木星", "ra_hours": 12.5, "dec_deg": 10.0, "altitude_deg": 45.0},
    }
    nl = build_intent_nl(raw)
    assert "木星" in nl["text"]
    assert "模拟" in nl["text"]


def test_cfw_list_nl() -> None:
    raw = {
        "ok": True,
        "action": "cfw_list",
        "filters": [{"slot": 1, "name": "Red"}, {"slot": 2, "name": "Green"}],
    }
    nl = build_intent_nl(raw)
    assert "Red" in nl["text"]
    assert "可用滤镜" in nl["text"]
