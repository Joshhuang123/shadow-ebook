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
    assert "minimax.cn" in client.base_url
    assert client.model == "MiniMax-M3.1-Flash-Preview"


def test_minimax_default_model_is_m31(monkeypatch):
    """默认 model 应该是 M3.1-Flash-Preview (官方文档 2026-09 推荐)。"""
    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-test")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    client = llm.get_llm_client()
    assert client.model == "MiniMax-M3.1-Flash-Preview"


def test_minimax_custom_model_via_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-test")
    monkeypatch.setenv("LLM_MODEL", "MiniMax-M3")
    client = llm.get_llm_client()
    assert client.model == "MiniMax-M3"


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


# === D1: retry on transient errors ===
def test_openai_compat_retries_on_500_then_succeeds(monkeypatch):
    """HTTP 500 第一次 → 重试 → 第二次 ok → 返回 content。"""
    client = llm.OpenAICompatClient(base_url="https://e.com", api_key="k", model="m")
    err = MagicMock()
    err.read.return_value = b"oops"
    http_500 = llm.urllib.error.HTTPError("url", 500, "Server Error", {}, err)
    ok_payload = {"choices": [{"message": {"content": "ok"}}]}
    ok_resp = _mock_urlopen_response(ok_payload)
    # 把 sleep 短路,免得测试真的等 0.5s
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    with patch("urllib.request.urlopen", side_effect=[http_500, ok_resp]) as m:
        result = client.chat([{"role": "user", "content": "x"}])
    assert result == "ok"
    assert m.call_count == 2


def test_openai_compat_no_retry_on_400(monkeypatch):
    """HTTP 400(配置错误)不重试,直接抛。"""
    client = llm.OpenAICompatClient(base_url="https://e.com", api_key="k", model="m")
    err = MagicMock()
    err.read.return_value = b"bad request"
    http_400 = llm.urllib.error.HTTPError("url", 400, "Bad Request", {}, err)
    with patch("urllib.request.urlopen", side_effect=http_400) as m:
        with pytest.raises(RuntimeError, match="HTTP 400"):
            client.chat([{"role": "user", "content": "x"}])
    assert m.call_count == 1


def test_openai_compat_retries_on_url_error(monkeypatch):
    """URLError(网络层)重试一次。"""
    client = llm.OpenAICompatClient(base_url="https://e.com", api_key="k", model="m")
    url_err = llm.urllib.error.URLError("connection refused")
    ok_resp = _mock_urlopen_response({"choices": [{"message": {"content": "ok"}}]})
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    with patch("urllib.request.urlopen", side_effect=[url_err, ok_resp]) as m:
        result = client.chat([{"role": "user", "content": "x"}])
    assert result == "ok"
    assert m.call_count == 2


def test_openai_compat_no_retry_when_first_call_succeeds(monkeypatch):
    """第一次成功就不该再调,retry 不应该无脑触发。"""
    client = llm.OpenAICompatClient(base_url="https://e.com", api_key="k", model="m")
    ok_resp = _mock_urlopen_response({"choices": [{"message": {"content": "ok"}}]})
    with patch("urllib.request.urlopen", return_value=ok_resp) as m:
        client.chat([{"role": "user", "content": "x"}])
    assert m.call_count == 1


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