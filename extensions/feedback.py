"""
Owns: post-recording AI feedback for tutor.html 跟读 page.
       ASR (whisper, optional/lazy-loaded) + LLM-generated structured feedback.
Does NOT own: tutor UI (web/js/tutor.js), TTS for original audio (tts.py), sentence mastery (parent_data.py).
"""
import difflib
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from flask import jsonify, request

from extensions.auth import _api_rate_limit_ok
from extensions.llm import get_llm_client
from extensions.parent_data import get_weak_words

logger = logging.getLogger(__name__)


# === Whisper 模型懒加载 (单例,首次请求才装,避免 import 时拖慢启动) ===
_WHISPER_MODEL = None
_WHISPER_MODEL_NAME = os.environ.get("WHISPER_MODEL", "base")  # base/small/medium/large


def _get_whisper():
    """懒加载 whisper 模型。失败抛 RuntimeError 让上层降级。"""
    global _WHISPER_MODEL
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL
    try:
        import whisper  # type: ignore
    except ImportError:
        raise RuntimeError(
            "whisper 未安装。运行: pip install openai-whisper (或 pip install -r requirements-dev.txt)"
        )
    logger.info(f"加载 whisper 模型 {_WHISPER_MODEL_NAME} (首次较慢)...")
    _WHISPER_MODEL = whisper.load_model(_WHISPER_MODEL_NAME)
    logger.info("whisper 模型加载完成")
    return _WHISPER_MODEL


# === LLM 输出 schema ===
FEEDBACK_JSON_SCHEMA = {
    "type": "object",
    "required": ["overall", "suggestion", "encouragement"],
    "additionalProperties": False,
    "properties": {
        "overall": {
            "type": "string",
            "minLength": 4,
            "maxLength": 100,
            "description": "一句话总体评价,例如:'整体不错,有 2 个词需要练习'",
        },
        "errors": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "required": ["got", "expected", "tip"],
                "additionalProperties": False,
                "properties": {
                    "got": {"type": "string", "description": "孩子实际读出的"},
                    "expected": {"type": "string", "description": "正确的"},
                    "tip": {"type": "string", "maxLength": 80, "description": "中文小贴士"},
                },
            },
            "description": "读错的词 (0-5 条)",
        },
        "suggestion": {
            "type": "string",
            "minLength": 4,
            "maxLength": 120,
            "description": "下次怎么读的简短建议,1-2 句话",
        },
        "encouragement": {
            "type": "string",
            "minLength": 4,
            "maxLength": 60,
            "description": "鼓励的话,1 句话,适合 8-12 岁孩子",
        },
    },
}


# === Prompt ===
_FEEDBACK_PROMPT = """你是给 8-12 岁中国孩子的英语跟读老师。看完下面信息给出鼓励性的反馈。

**原句 (孩子要读的):** "{sentence}"

**孩子实际读出的 (ASR 转写):** "{transcript}"

**整体相似度:** {similarity:.0%}  (越高越接近原句;读错音、漏词、多词都会降低)

**读错的词 (差异):**
{errors_block}

**孩子历史薄弱词 (家长追踪过的、错误率较高的):**
{weak_words_block}

请严格按下面的 JSON 格式输出,只输出 JSON,不要任何解释或 markdown 标记:

{{"overall": "一句话总体评价", "errors": [{{"got": "...", "expected": "...", "tip": "..."}}], "suggestion": "1-2 句建议", "encouragement": "1 句鼓励"}}

要求:
- 如果 errors 为空,overall 就说"读得很准",suggestion 说继续保持
- **如果薄弱词里有原句里的词,errors 里必须包含这条,且 tip 要明确针对这个薄弱点**(例:薄弱词"th",原句含"the",tip 说"th 要把舌尖放上齿背")
- 语气必须鼓励性,**永远不要**让孩子觉得自己很笨
- tip 用中文,30 字以内
- encouragement 必须包含一个 emoji"""


def _build_prompt(sentence: str, transcript: str, similarity: float,
                  error_pairs: list, weak_words: Optional[list] = None) -> str:
    if error_pairs:
        errors_block = "\n".join(f"- 实际:「{got}」→ 应该:「{exp}」" for got, exp in error_pairs[:5])
    else:
        errors_block = "(没有明显错误)"

    if weak_words:
        weak_words_block = "、".join(weak_words)
    else:
        weak_words_block = "(暂无历史数据,基于这次表现给反馈)"

    return _FEEDBACK_PROMPT.format(
        sentence=sentence,
        transcript=transcript,
        similarity=similarity,
        errors_block=errors_block,
        weak_words_block=weak_words_block,
    )


def _diff_words(sentence: str, transcript: str) -> list:
    """用 difflib 找 sentence 和 transcript 的词级差异。

    返回 [(got, expected), ...] 最多 5 条。
    """
    sent_words = sentence.lower().split()
    trans_words = transcript.lower().split()
    matcher = difflib.SequenceMatcher(None, sent_words, trans_words)
    pairs = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            # 取较短的边,避免 1 对多混乱
            for k in range(min(i2 - i1, j2 - j1)):
                pairs.append((trans_words[j1 + k], sent_words[i1 + k]))
        elif tag == "delete":
            # 原句有,孩子漏读了 → got="" expected=sent_words[i1+k]
            for k in range(i2 - i1):
                pairs.append(("", sent_words[i1 + k]))
        elif tag == "insert":
            # 孩子多读了 → got=trans_words[j1+k] expected=""
            for k in range(j2 - j1):
                pairs.append((trans_words[j1 + k], ""))
    return pairs[:5]


# === 路由 ===
def register_routes(app):
    @app.route('/api/recording/feedback', methods=['POST'])
    def recording_feedback():
        """跟读 AI 反馈。

        Form fields:
          audio    录音 webm 文件 (必填)
          sentence 原句 (必填)
          unit     单元标识 (可选,帮助 prompt 上下文)
        """
        if (resp := _rate_limited()):
            return resp

        audio_file = request.files.get('audio')
        sentence = (request.form.get('sentence') or '').strip()

        if not audio_file or not sentence:
            return jsonify({
                "success": False,
                "error": "缺少 audio 或 sentence",
                "retryable": False,
            }), 400

        # === Step 1: 保存到临时文件 (whisper 需要文件路径) ===
        suffix = Path(audio_file.filename or 'rec.webm').suffix or '.webm'
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            audio_file.save(tmp.name)
            tmp.close()

            # === Step 2a: 加载 whisper (没装 → 503,前端降级) ===
            try:
                model = _get_whisper()
            except RuntimeError as e:
                logger.warning(f"ASR 不可用: {e}")
                return jsonify({
                    "success": False,
                    "error": str(e),
                    "asr_available": False,
                    "retryable": False,
                }), 503

            # === Step 2b: 转写 (加载成功但本条录音失败 → 502,可重试) ===
            try:
                asr_result = model.transcribe(tmp.name, language='en', fp16=False)
                transcript = (asr_result.get('text') or '').strip()
            except Exception as e:
                logger.warning(f"ASR 转写失败: {type(e).__name__}: {e}")
                return jsonify({
                    "success": False,
                    "error": "语音识别失败",
                    "asr_available": True,
                    "retryable": True,
                    "retry_after": 3,
                }), 502
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

        if not transcript:
            return jsonify({
                "success": False,
                "error": "没听清,再试一次?",
                "transcript": "",
                "retryable": False,
            }), 400

        # === Step 3: 算相似度 + 找差异 ===
        similarity = difflib.SequenceMatcher(None, sentence.lower(), transcript.lower()).ratio()
        error_pairs = _diff_words(sentence, transcript)

        # === Step 4: LLM 生成反馈 ===
        try:
            client = get_llm_client()
            # R20: 拿孩子历史薄弱词喂进 prompt,让反馈个性化
            weak_words = get_weak_words(limit=10)
            prompt = _build_prompt(sentence, transcript, similarity, error_pairs, weak_words)
            feedback = client.chat_json(
                [{"role": "user", "content": prompt}],
                schema=FEEDBACK_JSON_SCHEMA,
            )
        except Exception as e:
            # LLM 失败 → 仍然返回 transcript + similarity,前端用静态 fallback
            logger.warning(f"LLM 反馈失败: {type(e).__name__}: {e}")
            return jsonify({
                "success": True,
                "transcript": transcript,
                "similarity": round(similarity, 2),
                "errors": [{"got": g, "expected": e, "tip": ""} for g, e in error_pairs],
                "feedback": None,
                "ai_unavailable": True,
            })

        return jsonify({
            "success": True,
            "transcript": transcript,
            "similarity": round(similarity, 2),
            "errors": [{"got": g, "expected": e, "tip": ""} for g, e in error_pairs],
            "feedback": feedback,
            "ai_unavailable": False,
        })


def _rate_limited():
    ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'global')
    if not ok:
        return jsonify({
            "success": False,
            "error": f"请求过快, {retry} 秒后再试",
            "retryable": True,
            "retry_after": retry,
        }), 429
    return None