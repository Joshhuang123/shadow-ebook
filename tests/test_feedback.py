"""tests/test_feedback.py — 跟读 AI 反馈测试。

跑:`pytest tests/test_feedback.py -v`

whisper 模型加载很慢,所有测试都 mock 掉,只测业务逻辑。
"""
import io
from unittest.mock import patch, MagicMock

import pytest

from extensions import feedback, llm


# === fixture ===
@pytest.fixture
def app(tmp_db):
    from flask import Flask
    flask_app = Flask(__name__)
    flask_app.config['TESTING'] = True
    flask_app.config['SECRET_KEY'] = 'test-secret'
    flask_app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
    feedback.register_routes(flask_app)
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _audio_bytes() -> bytes:
    """假音频数据。whisper 是 mock,内容无所谓。"""
    return b'\x1a\x45\xdf\xa3' + b'\x00' * 100  # EBML header + silence


def _post_audio(client, sentence="What are you doing?", **extra):
    data = {
        'audio': (io.BytesIO(_audio_bytes()), 'rec.webm'),
        'sentence': sentence,
    }
    data.update(extra)
    return client.post('/api/recording/feedback', data=data, content_type='multipart/form-data')


def _fake_whisper_model(transcript: str = "What are you doing?"):
    """构造 mock whisper 模型对象。"""
    model = MagicMock()
    model.transcribe.return_value = {"text": transcript, "segments": []}
    return model


# === happy path ===
def test_happy_path_returns_ai_feedback(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    with patch.object(feedback, '_get_whisper', return_value=_fake_whisper_model()):
        with patch.object(feedback, 'get_llm_client') as g:
            fake_llm = MagicMock(spec=llm.BaseLLMClient)
            fake_llm.chat_json.return_value = {
                "overall": "读得很准",
                "errors": [],
                "suggestion": "继续保持",
                "encouragement": "加油!💪",
            }
            g.return_value = fake_llm
            resp = _post_audio(client)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["transcript"] == "What are you doing?"
    assert data["ai_unavailable"] is False
    assert data["feedback"]["overall"] == "读得很准"


# === whisper 不可用 ===
def test_whisper_not_installed_returns_503(client, monkeypatch):
    def fake_get():
        raise RuntimeError("whisper 未安装。运行: pip install openai-whisper")
    with patch.object(feedback, '_get_whisper', side_effect=fake_get):
        resp = _post_audio(client)
    assert resp.status_code == 503
    data = resp.get_json()
    assert data["asr_available"] is False
    assert "whisper" in data["error"].lower()


def test_whisper_transcribe_fails_returns_502(client, monkeypatch):
    model = MagicMock()
    model.transcribe.side_effect = RuntimeError("ffmpeg crashed")
    with patch.object(feedback, '_get_whisper', return_value=model):
        resp = _post_audio(client)
    assert resp.status_code == 502
    data = resp.get_json()
    assert data["asr_available"] is True
    assert data["retryable"] is True


# === 空转写 ===
def test_empty_transcript_returns_400(client):
    with patch.object(feedback, '_get_whisper', return_value=_fake_whisper_model("")):
        resp = _post_audio(client)
    assert resp.status_code == 400
    assert "没听清" in resp.get_json()["error"]


# === 缺参数 ===
def test_missing_audio_returns_400(client):
    resp = client.post('/api/recording/feedback', data={
        'sentence': 'hello',
    }, content_type='multipart/form-data')
    assert resp.status_code == 400


def test_missing_sentence_returns_400(client):
    resp = client.post('/api/recording/feedback', data={
        'audio': (io.BytesIO(_audio_bytes()), 'rec.webm'),
    }, content_type='multipart/form-data')
    assert resp.status_code == 400


# === LLM 失败 → 仍然返回 transcript + null feedback ===
def test_llm_failure_returns_transcript_without_feedback(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    with patch.object(feedback, '_get_whisper', return_value=_fake_whisper_model("What are you doing")):
        with patch.object(feedback, 'get_llm_client') as g:
            fake_llm = MagicMock(spec=llm.BaseLLMClient)
            fake_llm.chat_json.side_effect = RuntimeError("upstream 503")
            g.return_value = fake_llm
            resp = _post_audio(client, sentence="What are you doing?")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["transcript"] == "What are you doing"
    assert data["feedback"] is None
    assert data["ai_unavailable"] is True
    # 相似度应该算出来 (高,因为几乎匹配)
    assert data["similarity"] > 0.8


# === _diff_words ===
def test_diff_words_finds_substitutions():
    pairs = feedback._diff_words("I am reading a book", "I am writting a book")
    # "reading" → "writting" 应该被识别为替换
    assert any("writting" == got and "reading" == exp for got, exp in pairs)


def test_diff_words_finds_deletions():
    pairs = feedback._diff_words("I am reading", "I reading")
    # "am" 漏读了
    assert any(got == "" and exp == "am" for got, exp in pairs)


def test_diff_words_caps_at_five():
    sentence = "a b c d e f g h"
    transcript = "x y z q w r s t"  # 全部替换
    pairs = feedback._diff_words(sentence, transcript)
    assert len(pairs) <= 5


def test_diff_words_no_diff():
    pairs = feedback._diff_words("hello world", "hello world")
    assert pairs == []


# === prompt 构建 ===
def test_prompt_includes_all_fields():
    prompt = feedback._build_prompt(
        sentence="What are you doing?",
        transcript="What you doing",
        similarity=0.85,
        error_pairs=[("you", "are")],
    )
    assert "What are you doing?" in prompt
    assert "What you doing" in prompt
    assert "85%" in prompt
    assert "What you" in prompt or "you" in prompt
    assert "are" in prompt


def test_prompt_handles_no_errors():
    prompt = feedback._build_prompt(
        sentence="Hello",
        transcript="Hello",
        similarity=1.0,
        error_pairs=[],
    )
    assert "没有明显错误" in prompt
    assert "100%" in prompt


# === JSON schema ===
def test_schema_accepts_valid_feedback():
    import jsonschema
    good = {
        "overall": "读得很不错",
        "errors": [{"got": "writting", "expected": "writing", "tip": "双 t"}],
        "suggestion": "注意 -ing 拼写",
        "encouragement": "加油!🌟",
    }
    jsonschema.validate(good, feedback.FEEDBACK_JSON_SCHEMA)


def test_schema_rejects_missing_required():
    import jsonschema
    bad = {"overall": "整体不错"}  # 缺 suggestion + encouragement
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, feedback.FEEDBACK_JSON_SCHEMA)


def test_schema_accepts_no_errors():
    import jsonschema
    good = {
        "overall": "读得非常好",
        "errors": [],
        "suggestion": "继续保持",
        "encouragement": "太棒了!🎉",
    }
    jsonschema.validate(good, feedback.FEEDBACK_JSON_SCHEMA)


def test_schema_rejects_too_many_errors():
    import jsonschema
    bad = {
        "overall": "x",
        "errors": [{"got": f"w{i}", "expected": f"e{i}", "tip": "t"} for i in range(10)],
        "suggestion": "x",
        "encouragement": "x",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, feedback.FEEDBACK_JSON_SCHEMA)


# === similarity 计算 ===
def test_similarity_perfect():
    import difflib
    sim = difflib.SequenceMatcher(None, "hello world", "hello world").ratio()
    assert sim == 1.0


def test_similarity_partial():
    import difflib
    sim = difflib.SequenceMatcher(None, "What are you doing", "What you doing").ratio()
    assert 0.7 < sim < 1.0


# === 限流 ===
def test_endpoint_rate_limited(client, monkeypatch, clear_api_rate):
    monkeypatch.setattr(
        "extensions.feedback._api_rate_limit_ok",
        lambda ip, bucket: (False, 30),
    )
    resp = _post_audio(client)
    assert resp.status_code == 429

# === R20: 薄弱词喂回 prompt ===
def test_build_prompt_includes_weak_words():
    prompt = feedback._build_prompt(
        sentence="What are you doing?",
        transcript="What are you doing",
        similarity=0.95,
        error_pairs=[],
        weak_words=["th", "the", "they"],
    )
    assert "th" in prompt
    assert "the" in prompt
    assert "they" in prompt
    assert "薄弱词" in prompt


def test_build_prompt_handles_empty_weak_words():
    prompt = feedback._build_prompt(
        sentence="Hello",
        transcript="Hello",
        similarity=1.0,
        error_pairs=[],
        weak_words=None,
    )
    assert "暂无历史数据" in prompt


def test_build_prompt_default_weak_words_is_empty():
    """不传 weak_words 时,默认行为应该是"暂无历史数据"占位。"""
    prompt = feedback._build_prompt(
        sentence="Hello", transcript="Hello", similarity=1.0, error_pairs=[],
    )
    assert "暂无历史数据" in prompt


def test_endpoint_passes_weak_words_to_llm(client, monkeypatch):
    """端点应该调 get_weak_words 并把结果塞进 LLM 的 prompt。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    with patch.object(feedback, '_get_whisper', return_value=_fake_whisper_model("What are you doing?")):
        with patch.object(feedback, 'get_llm_client') as g:
            fake_llm = MagicMock(spec=llm.BaseLLMClient)
            fake_llm.chat_json.return_value = {
                "overall": "好", "errors": [],
                "suggestion": "继续", "encouragement": "加油!🌟",
            }
            g.return_value = fake_llm
            with patch.object(feedback, 'get_weak_words', return_value=["th", "they"]) as gw:
                resp = _post_audio(client, sentence="What are you doing?")
    assert resp.status_code == 200
    assert gw.called, '端点应该调 get_weak_words'
    # LLM 收到的 prompt 应该包含薄弱词
    call_args = fake_llm.chat_json.call_args
    prompt_text = call_args[0][0][0]["content"]
    assert "th" in prompt_text
    assert "they" in prompt_text


def test_endpoint_works_when_no_weak_words(client, monkeypatch):
    """没薄弱词(新用户)时不应该崩。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    with patch.object(feedback, '_get_whisper', return_value=_fake_whisper_model("Hello")):
        with patch.object(feedback, 'get_llm_client') as g:
            fake_llm = MagicMock(spec=llm.BaseLLMClient)
            fake_llm.chat_json.return_value = {
                "overall": "好", "errors": [],
                "suggestion": "继续", "encouragement": "加油!🌟",
            }
            g.return_value = fake_llm
            with patch.object(feedback, 'get_weak_words', return_value=[]):
                resp = _post_audio(client, sentence="Hello")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
