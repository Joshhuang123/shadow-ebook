"""tests/test_llm.py — LLM 抽象层测试。

跑:`pytest tests/test_llm.py -v`
"""
import json
import os
from unittest.mock import patch, MagicMock

import pytest

from extensions import llm


# === 工厂 ===
def test_get_llm_client_deepseek_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    client = llm.get_llm_client()
    assert isinstance(client, llm.DeepSeekClient)
    assert client.model == "deepseek-chat"
    assert "deepseek.com" in client.base_url


def test_get_llm_client_deepseek_custom_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "deepseek-reasoner")
    client = llm.get_llm_client()
    assert client.model == "deepseek-reasoner"


def test_get_llm_client_minimax(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-test")
    client = llm.get_llm_client()
    assert isinstance(client, llm.MiniMaxClient)
    assert "minimaxi.com" in client.base_url


def test_get_llm_client_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gpt-99")
    with pytest.raises(RuntimeError, match="未知 LLM_PROVIDER"):
        llm.get_llm_client()


def test_get_llm_client_missing_api_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="api_key 未配置"):
        llm.get_llm_client()


# === OpenAICompatClient.chat ===
def _mock_urlopen_response(payload: dict):
    """构造 urlopen 返回的 context manager。"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = lambda s, *a: False
    return mock_resp


def test_openai_compat_chat_success(monkeypatch):
    client = llm.OpenAICompatClient(
        base_url="https://example.com/v1",
        api_key="test-key",
        model="test-model",
    )
    payload = {"choices": [{"message": {"content": "hello"}}]}
    with patch("urllib.request.urlopen", return_value=_mock_urlopen_response(payload)) as m:
        result = client.chat([{"role": "user", "content": "hi"}])
    assert result == "hello"
    # 验证请求体
    req = m.call_args[0][0]
    assert req.method == "POST"
    assert req.headers["Authorization"] == "Bearer test-key"
    body = json.loads(req.data)
    assert body["model"] == "test-model"
    assert body["temperature"] == 0.3


def test_openai_compat_chat_http_error(monkeypatch):
    client = llm.OpenAICompatClient(base_url="https://e.com", api_key="k", model="m")
    err = MagicMock()
    err.read.return_value = b"upstream error"
    http_err = llm.urllib.error.HTTPError("url", 500, "Server Error", {}, err)
    with patch("urllib.request.urlopen", side_effect=http_err):
        with pytest.raises(RuntimeError, match="LLM upstream HTTP 500"):
            client.chat([{"role": "user", "content": "x"}])


def test_openai_compat_chat_malformed_payload():
    client = llm.OpenAICompatClient(base_url="https://e.com", api_key="k", model="m")
    bad = {"oops": "no choices key"}
    with patch("urllib.request.urlopen", return_value=_mock_urlopen_response(bad)):
        with pytest.raises(RuntimeError, match="malformed response"):
            client.chat([{"role": "user", "content": "x"}])


# === _parse_and_validate ===
def test_parse_and_validate_clean_json():
    raw = '{"q": "test", "o": ["a", "b"], "a": 0}'
    schema = {
        "type": "object",
        "required": ["q", "o", "a"],
        "properties": {
            "q": {"type": "string"},
            "o": {"type": "array", "items": {"type": "string"}},
            "a": {"type": "integer"},
        },
    }
    obj = llm._parse_and_validate(raw, schema)
    assert obj["q"] == "test"


def test_parse_and_validate_strips_code_fence():
    raw = '```json\n{"q": "test", "o": ["a"], "a": 0}\n```'
    schema = {
        "type": "object",
        "required": ["q", "o", "a"],
        "properties": {
            "q": {"type": "string"},
            "o": {"type": "array"},
            "a": {"type": "integer"},
        },
    }
    obj = llm._parse_and_validate(raw, schema)
    assert obj["q"] == "test"


def test_parse_and_validate_invalid_json():
    with pytest.raises(RuntimeError, match="invalid JSON"):
        llm._parse_and_validate("{not valid json}", {})


def test_parse_and_validate_schema_mismatch():
    raw = '{"q": 123}'  # q 应该是 string
    schema = {
        "type": "object",
        "required": ["q"],
        "properties": {"q": {"type": "string"}},
    }
    with pytest.raises(RuntimeError, match="schema mismatch"):
        llm._parse_and_validate(raw, schema)


# === chat_json 默认实现 ===
def test_chat_json_default_uses_parse_and_validate():
    client = llm.OpenAICompatClient(base_url="https://e.com", api_key="k", model="m")
    payload = {"choices": [{"message": {"content": '{"q": "x", "o": ["a"], "a": 0}'}}]}
    schema = {
        "type": "object",
        "required": ["q", "o", "a"],
        "properties": {
            "q": {"type": "string"},
            "o": {"type": "array"},
            "a": {"type": "integer"},
        },
    }
    with patch("urllib.request.urlopen", return_value=_mock_urlopen_response(payload)):
        obj = client.chat_json([{"role": "user", "content": "x"}], schema)
    assert obj["q"] == "x"