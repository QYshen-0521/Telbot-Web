"""Rule-fast paths for common voice phrases (no LLM / semantic)."""

from telbot.text_intent import parse_intent_zh


def test_exoplanet_transits_rule_phrases() -> None:
    for s in (
        "今晚有哪些系外行星凌星",
        "今晚有哪些系外行星观测事件",
        "今晚可观测的系外行星事件有哪些",
        "查询今晚凌星事件",
        "今夜有什么凌星",
    ):
        v = parse_intent_zh(s)
        assert v is not None, s
        assert v.action == "exoplanet_transits", s


def test_plan_exoplanet_transit_rule_phrases() -> None:
    cases = (
        ("帮我规划第1个凌星", 1),
        ("帮我规划第一个凌星", 1),
        ("规划第2个凌星", 2),
        ("帮我规划凌星观测", 1),
    )
    for s, idx in cases:
        v = parse_intent_zh(s)
        assert v is not None, s
        assert v.action == "plan_exoplanet_transit", s
        if idx is not None:
            assert v.event_index == idx, s
    v_wasp = parse_intent_zh("今晚观测 WASP-12 b 凌星")
    assert v_wasp is not None
    assert v_wasp.action == "plan_exoplanet_transit"
    assert "WASP-12" in (v_wasp.target or "")


def test_goto_rule_phrases() -> None:
    cases = (
        ("帮我指向木星", "jupiter"),
        ("帮我指向M31", "M31"),
        ("请帮我指向土星", "saturn"),
        ("指向M31", "M31"),
        ("我要看火星", "mars"),
        ("帮我把望远镜对准月球", "moon"),
    )
    for s, target in cases:
        v = parse_intent_zh(s)
        assert v is not None, s
        assert v.action == "goto", s
        assert v.target == target, s


def test_goto_vague_not_matched() -> None:
    assert parse_intent_zh("帮我指向某个目标") is None
