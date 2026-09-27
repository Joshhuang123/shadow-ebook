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

# === R21: generated_questions 缓存 ===
def test_first_request_misses_cache_then_saves(client, monkeypatch):
    """第一次请求某个 (user, key) → cache miss → LLM 被调 → 题目被存进缓存。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    fake_question = {
        "q": "She ___ to school. (go)",
        "o": ["go", "goes", "going"],
        "a": 1,
    }
    fake_client = MagicMock(spec=llm.BaseLLMClient)
    fake_client.chat_json.return_value = fake_question
    with patch("extensions.grammar_quiz.get_llm_client", return_value=fake_client):
        resp = client.get("/api/grammar/question/ket-present-simple")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["source"] == "llm"

    # 验证已落库
    from extensions.db import get_db
    row = get_db().execute(
        "SELECT * FROM generated_questions WHERE user_id='default' AND grammar_key='ket-present-simple'"
    ).fetchone()
    assert row is not None
    assert row['used_count'] == 0  # 刚存的还没被用过


def test_second_request_hits_cache_no_llm_call(client, monkeypatch):
    """第二次同 key 请求 → cache hit → LLM 不被调,used_count +1。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    fake_client = MagicMock(spec=llm.BaseLLMClient)
    fake_client.chat_json.return_value = {
        "q": "Q1", "o": ["a", "b"], "a": 0,
    }
    with patch("extensions.grammar_quiz.get_llm_client", return_value=fake_client):
        # 第一次:cache miss
        client.get("/api/grammar/question/ket-present-simple")
        fake_client.chat_json.reset_mock()

        # 第二次:cache hit
        resp = client.get("/api/grammar/question/ket-present-simple")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["source"] == "cache"
    assert data["question"]["q"] == "Q1"
    assert not fake_client.chat_json.called, 'cache hit 时不应再调 LLM'

    # used_count 应该 +1
    from extensions.db import get_db
    row = get_db().execute(
        "SELECT used_count FROM generated_questions WHERE question_text='Q1'"
    ).fetchone()
    assert row['used_count'] == 1


def test_cache_excludes_seen_questions(client, monkeypatch):
    """exclude 列表里的题不会被缓存返回。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    fake_client = MagicMock(spec=llm.BaseLLMClient)
    # LLM 返回唯一题
    fake_client.chat_json.return_value = {
        "q": "Only question", "o": ["a", "b"], "a": 0,
    }
    with patch("extensions.grammar_quiz.get_llm_client", return_value=fake_client):
        client.get("/api/grammar/question/ket-present-simple")
        # 第二次:exclude 这道题 → 缓存命中但应被跳过,fallback 到 LLM
        fake_client.chat_json.reset_mock()
        fake_client.chat_json.return_value = {
            "q": "Second question", "o": ["a", "b"], "a": 0,
        }
        resp = client.get("/api/grammar/question/ket-present-simple?exclude=" + json.dumps(["Only question"]))
    assert resp.get_json()["source"] == "llm"
    assert fake_client.chat_json.called, '缓存全被 exclude 时应回退到 LLM'


def test_cache_save_failure_doesnt_break_response(client, monkeypatch):
    """_save_question 失败时,用户依然拿到题目。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    fake_client = MagicMock(spec=llm.BaseLLMClient)
    fake_client.chat_json.return_value = {
        "q": "X", "o": ["a"], "a": 0,
    }
    # mock _save_question 抛错
    with patch("extensions.grammar_quiz.get_llm_client", return_value=fake_client):
        with patch("extensions.grammar_quiz._save_question", side_effect=RuntimeError("db down")):
            resp = client.get("/api/grammar/question/ket-present-simple")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


# === 缓存 helpers 单元测试 ===
def test_save_then_get_returns_cached_question(tmp_db):
    question = {"q": "Test Q", "o": ["a", "b", "c"], "a": 1}
    assert grammar_quiz._save_question("user1", "ket-x", question) is True

    cached = grammar_quiz._get_cached_question("user1", "ket-x", [])
    assert cached is not None
    assert cached['question']['q'] == "Test Q"


def test_get_cached_returns_none_when_empty(tmp_db):
    assert grammar_quiz._get_cached_question("nobody", "nothing", []) is None


def test_get_cached_skips_excluded(tmp_db):
    q = {"q": "Q1", "o": ["a"], "a": 0}
    grammar_quiz._save_question("u", "k", q)
    assert grammar_quiz._get_cached_question("u", "k", ["Q1"]) is None
    assert grammar_quiz._get_cached_question("u", "k", ["other"]) is not None


def test_get_cached_skips_mastered_questions(tmp_db, monkeypatch):
    """used_count >= MASTERED_THRESHOLD 的题不应被返回(视为已掌握)。"""
    monkeypatch.setattr(grammar_quiz, 'MASTERED_THRESHOLD', 2)
    grammar_quiz._save_question("u", "k", {"q": "Q1", "o": ["a"], "a": 0})

    # 用 2 次
    grammar_quiz._increment_usage(1)
    grammar_quiz._increment_usage(1)

    # 再次查 → 应该拿不到这道(已毕业)
    cached = grammar_quiz._get_cached_question("u", "k", [])
    assert cached is None


def test_unique_constraint_prevents_duplicates(tmp_db):
    """同一 (user, key, q_text) 不能存两次。"""
    q = {"q": "Same Q", "o": ["a"], "a": 0}
    assert grammar_quiz._save_question("u", "k", q) is True
    # 第二次写应该被 UNIQUE 拦住,返回 False
    assert grammar_quiz._save_question("u", "k", q) is False


def test_eviction_when_over_max(tmp_db, monkeypatch):
    """超过 MAX_QUESTIONS_PER_KEY 时淘汰 used_count 最高 + 最老的。"""
    monkeypatch.setattr(grammar_quiz, 'MAX_QUESTIONS_PER_KEY', 3)
    # 存 4 道,每道 used_count 不同
    for i in range(4):
        grammar_quiz._save_question("u", "k", {"q": f"Q{i}", "o": ["a"], "a": 0})
    grammar_quiz._increment_usage(1)  # Q0 used 1 次
    grammar_quiz._increment_usage(1)
    grammar_quiz._increment_usage(1)  # Q0 used 3 次(最多)

    # 现在应该有 3 道 (Q1, Q2, Q3),Q0 被淘汰
    from extensions.db import get_db
    count = get_db().execute(
        "SELECT COUNT(*) c FROM generated_questions WHERE user_id='u' AND grammar_key='k'"
    ).fetchone()['c']
    assert count == 3
    # Q0 应该没了
    q0 = get_db().execute(
        "SELECT * FROM generated_questions WHERE question_text='Q0'"
    ).fetchone()
    assert q0 is None


def test_increment_usage_idempotent_on_missing_id(tmp_db):
    """不存在的 id 不应崩。"""
    grammar_quiz._increment_usage(99999)  # 没异常就是通过


def test_different_users_have_independent_caches(tmp_db):
    """user1 的缓存不影响 user2。"""
    grammar_quiz._save_question("user1", "k", {"q": "Q1", "o": ["a"], "a": 0})
    grammar_quiz._save_question("user2", "k", {"q": "Q2", "o": ["a"], "a": 0})
    c1 = grammar_quiz._get_cached_question("user1", "k", [])
    c2 = grammar_quiz._get_cached_question("user2", "k", [])
    assert c1['question']['q'] == "Q1"
    assert c2['question']['q'] == "Q2"


def test_different_keys_have_independent_caches(tmp_db):
    grammar_quiz._save_question("u", "ket-x", {"q": "Q1", "o": ["a"], "a": 0})
    grammar_quiz._save_question("u", "ket-y", {"q": "Q2", "o": ["a"], "a": 0})
    cx = grammar_quiz._get_cached_question("u", "ket-x", [])
    cy = grammar_quiz._get_cached_question("u", "ket-y", [])
    assert cx['question']['q'] == "Q1"
    assert cy['question']['q'] == "Q2"
