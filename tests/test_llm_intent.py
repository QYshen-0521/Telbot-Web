from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from telbot.config import Settings
from telbot.llm_intent import _parse_llm_json, _strip_json_fences, resolve_intent_llm


def test_strip_json_fences() -> None:
    assert _strip_json_fences('{"a":1}') == '{"a":1}'
    fenced = "```json\n{\"x\":2}\n```"
    assert _strip_json_fences(fenced) == '{"x":2}'
    assert _parse_llm_json(fenced) == {"x": 2}


def test_resolve_intent_llm_no_key() -> None:
    s = Settings(intent_use_llm=False, llm_api_key="", openai_api_key="")
    assert resolve_intent_llm("我要看木星", s) is None


def test_resolve_intent_llm_mock_openai() -> None:
    pytest.importorskip("openai", reason="LLM 意图测试需 openai 包（见 pip install -e '.[llm]'）")
    s = Settings(
        intent_use_llm=True,
        llm_api_key="sk-test",
        llm_base_url="https://api.siliconflow.cn/v1",
        llm_model="Qwen/Qwen2.5-7B-Instruct",
    )
    payload = '{"version":1,"action":"goto","target":"木星","frame":"JNOW","confidence":0.9}'
    fake_msg = MagicMock()
    fake_msg.content = payload
    fake_choice = MagicMock()
    fake_choice.message = fake_msg
    fake_completion = MagicMock()
    fake_completion.choices = [fake_choice]

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_completion

    with patch("openai.OpenAI", return_value=fake_client):
        intent = resolve_intent_llm("我要看木星", s)

    assert intent is not None
    assert intent.action == "goto"
    assert intent.target == "木星"
    assert intent.raw_text == "我要看木星"
    fake_client.chat.completions.create.assert_called()


def test_resolve_intent_unparseable_mock() -> None:
    pytest.importorskip("openai", reason="LLM 意图测试需 openai 包（见 pip install -e '.[llm]'）")
    s = Settings(llm_api_key="sk-x", llm_base_url="https://example.com/v1")
    fake_msg = MagicMock()
    fake_msg.content = '{"unparseable":true}'
    fake_choice = MagicMock()
    fake_choice.message = fake_msg
    fake_completion = MagicMock()
    fake_completion.choices = [fake_choice]
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_completion

    with patch("openai.OpenAI", return_value=fake_client):
        assert resolve_intent_llm("随便闲聊", s) is None
