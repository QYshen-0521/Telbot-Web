import io

from rich.console import Console

from telbot.config import Settings
from telbot.nl_pipeline import resolve_intent_from_sentence


def test_resolve_intent_rules_hit_no_semantic() -> None:
    s = Settings()
    buf = io.StringIO()
    c = Console(file=buf, width=120, color_system=None)
    intent = resolve_intent_from_sentence(
        "我要看木星",
        s,
        console=c,
        no_semantic=True,
        semantic_only=False,
    )
    assert intent is not None
    assert intent.action == "goto"
    assert intent.target == "jupiter"


def test_resolve_intent_empty() -> None:
    s = Settings()
    c = Console(file=io.StringIO(), width=80, color_system=None)
    assert resolve_intent_from_sentence("   ", s, console=c, no_semantic=True, semantic_only=False) is None
