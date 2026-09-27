"""tests/test_grammar_quiz.py — 动态语法出题测试。

跑:`pytest tests/test_grammar_quiz.py -v`
"""
import json
from unittest.mock import patch, MagicMock

import pytest

from extensions import grammar_quiz, llm


# === fixture: Flask test app ===
@pytest.fixture
def app(tmp_db):
    """最小 Flask app,只挂 grammar_quiz 路由,跑测试不污染其他 extension。"""
    from flask import Flask
    flask_app = Flask(__name__)
    flask_app.config['TESTING'] = True
    flask_app.config['SECRET_KEY'] = 'test-secret'
    grammar_quiz.register_routes(flask_app)
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


# === 端点:LLM 成功 ===
def test_endpoint_returns_llm_question(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    fake_question = {
        "q": "She ___ to school. (go)",
        "o": ["go", "goes", "going"],
        "a": 1,
        "explanation": "第三人称单数加 -s",
    }
    fake_client = MagicMock(spec=llm.BaseLLMClient)
    fake_client.chat_json.return_value = fake_question
    with patch("extensions.grammar_quiz.get_llm_client", return_value=fake_client):
        resp = client.get("/api/grammar/question/ket-present-simple")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["source"] == "llm"
    assert data["question"]["a"] == 1


# === 端点:LLM 失败 → 静态 fallback ===
def test_endpoint_falls_back_to_static_on_llm_error(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    fake_client = MagicMock(spec=llm.BaseLLMClient)
    fake_client.chat_json.side_effect = RuntimeError("upstream down")
    with patch("extensions.grammar_quiz.get_llm_client", return_value=fake_client):
        resp = client.get("/api/grammar/question/ket-present-simple")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["source"] == "static"
    # 静态题库 ket-present-simple 有 2 题
    assert data["question"]["q"]


# === 端点:LLM 和静态都不可用 ===
def test_endpoint_returns_503_when_no_fallback(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    fake_client = MagicMock(spec=llm.BaseLLMClient)
    fake_client.chat_json.side_effect = RuntimeError("down")
    # 选一个静态题库没覆盖的 key(将来加了 LLM-only 的 key 就能触发)
    with patch("extensions.grammar_quiz.get_llm_client", return_value=fake_client):
        # 临时清掉一个 key 的静态题,模拟"只有 LLM 能出题"的场景
        original = grammar_quiz.STATIC_QUESTION_BANK
        grammar_quiz.STATIC_QUESTION_BANK = {"ket-present-simple": []}
        try:
            resp = client.get("/api/grammar/question/ket-present-simple")
        finally:
            grammar_quiz.STATIC_QUESTION_BANK = original
    assert resp.status_code == 503
    assert "LLM 不可用" in resp.get_json()["error"]


# === 端点:未知 key ===
def test_endpoint_404_unknown_key(client):
    resp = client.get("/api/grammar/question/this-key-does-not-exist")
    assert resp.status_code == 404
    assert "未知语法点" in resp.get_json()["error"]


# === 端点:exclude 解析 ===
def test_endpoint_exclude_param_skips_seen(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    fake_client = MagicMock(spec=llm.BaseLLMClient)
    fake_client.chat_json.return_value = {
        "q": "NEW question", "o": ["a", "b", "c"], "a": 0,
    }
    with patch("extensions.grammar_quiz.get_llm_client", return_value=fake_client):
        resp = client.get(
            "/api/grammar/question/ket-present-simple?exclude=" + json.dumps(["OLD question"])
        )
    assert resp.status_code == 200
    # 验证 LLM 收到的 prompt 包含 exclude 块
    call_args = fake_client.chat_json.call_args
    messages = call_args[0][0]
    prompt_text = messages[0]["content"]
    assert "OLD question" in prompt_text


# === 端点:exclude 解析失败时 fallback 到空 ===
def test_endpoint_exclude_malformed_falls_back(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    fake_client = MagicMock(spec=llm.BaseLLMClient)
    fake_client.chat_json.return_value = {
        "q": "test", "o": ["a", "b"], "a": 0,
    }
    with patch("extensions.grammar_quiz.get_llm_client", return_value=fake_client):
        resp = client.get("/api/grammar/question/ket-present-simple?exclude=not-json")
    assert resp.status_code == 200
    # LLM 应该被调用,prompt 不含 malformed exclude 文本
    assert fake_client.chat_json.called


# === prompt 内容 ===
def test_prompt_includes_description_and_exclusion():
    system, user = grammar_quiz._build_prompt(
        "ket-present-simple",
        ["old question 1", "old question 2"],
    )
    assert "Present Simple" in user
    assert "第三人称单数" in user
    assert "old question 1" in user
    assert "JSON" in user  # 强调只输出 JSON


def test_prompt_unknown_key_returns_empty():
    system, user = grammar_quiz._build_prompt("this-key-does-not-exist", [])
    assert user == ""


# === JSON schema 校验 ===
def test_json_schema_rejects_bad_payload():
    # 缺 a 字段
    bad = {"q": "test", "o": ["a", "b"]}
    import jsonschema
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, grammar_quiz.GRAMMAR_QUESTION_JSON_SCHEMA)


def test_json_schema_accepts_minimal_payload():
    import jsonschema
    good = {"q": "She ___ to school every day. (go)", "o": ["go", "goes", "going"], "a": 1}
    jsonschema.validate(good, grammar_quiz.GRAMMAR_QUESTION_JSON_SCHEMA)


def test_json_schema_rejects_answer_out_of_range():
    import jsonschema
    bad = {"q": "test", "o": ["a", "b"], "a": 5}  # a >= o.length
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, grammar_quiz.GRAMMAR_QUESTION_JSON_SCHEMA)


# === _try_static_fallback ===
def test_static_fallback_avoids_excluded():
    questions = grammar_quiz._try_static_fallback("ket-present-simple", [
        "She ___ English every day. (like)",
    ])
    assert questions is not None
    # 排除后剩 1 道
    assert "every day" not in questions["q"]


def test_static_fallback_cycles_when_all_seen():
    all_seen = [
        "She ___ English every day. (like)",
        "When ___ you get up? (do)",
    ]
    questions = grammar_quiz._try_static_fallback("ket-present-simple", all_seen)
    # 全做过了 → 循环(随机抽一道)
    assert questions is not None


def test_static_fallback_returns_none_for_unknown_key():
    assert grammar_quiz._try_static_fallback("this-key-does-not-exist", []) is None


# === 限流 ===
def test_endpoint_rate_limited(client, monkeypatch, clear_api_rate):
    """短时间大量请求应该被 global 桶挡住。"""
    # global 桶上限 600/min;这里 mock 让其直接返回 False
    monkeypatch.setattr(
        "extensions.grammar_quiz._api_rate_limit_ok",
        lambda ip, bucket: (False, 30),
    )
    resp = client.get("/api/grammar/question/ket-present-simple")
    assert resp.status_code == 429
    assert resp.get_json()["retryable"] is True