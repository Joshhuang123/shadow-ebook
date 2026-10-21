"""
Owns: post-recording AI feedback for tutor.html 跟读 page.
       ASR (whisper, optional/lazy-loaded) + LLM-generated structured feedback.
Does NOT own: tutor UI (web/js/tutor.js), TTS for original audio (tts.py), sentence mastery (parent_data.py).
"""
import difflib
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from flask import jsonify, request

from extensions.auth import _api_rate_limit_ok
from extensions.llm import get_llm_client
from extensions.parent_data import get_weak_words

logger = logging.getLogger(__name__)

# 单词:只留字母和撇号 —— 和 phonemes._WORD_RE 保持一致
_WORD_RE = re.compile(r"[a-z']+")


# === ASR 模型懒加载 (单例,首次请求才装,避免 import 时拖慢启动) ===
_ASR = None
# 模型大小:tiny / base / small / medium / large
# 体积差得很远(tiny ~75MB,base ~145MB,small ~480MB,large ~1.5GB),
# 而孩子的句子很短,base 够用;要更小就改 tiny。
_WHISPER_MODEL_NAME = os.environ.get("WHISPER_MODEL", "base")
# 用哪个后端:
#   faster(默认)—— CTranslate2,不需要 torch,省 2~3GB
#   openai       —— 官方包,要 torch
#   auto         —— 有 faster 就用 faster,否则退化到 openai
_WHISPER_BACKEND = os.environ.get("WHISPER_BACKEND", "auto")
# CPU 上用 int8 量化:体积和速度都更好,识别精度对短句影响很小
_WHISPER_COMPUTE = os.environ.get("WHISPER_COMPUTE", "int8")
# beam=1(贪心)最快;句子短,贪心足够
_WHISPER_BEAM = int(os.environ.get("WHISPER_BEAM", "1"))
# 模型缓存目录(想放外置盘就改这个)。
# 默认 ~/.cache/shadow-whisper —— 里面直接放 <模型名>/ 的目录结构。
_WHISPER_CACHE = (os.environ.get("WHISPER_CACHE_DIR")
                  or os.path.expanduser("~/.cache/shadow-whisper"))
_WHISPER_LOCK = threading.Lock()  # 防 Flask threaded 下并发首调加载两遍


class _FasterWhisperAdapter:
    """把 faster-whisper 的 API 包装成和 openai-whisper 一样的形状。

    为什么要这层:两个包都能用,但 API 不一样(一个是 dict,
    一个是 segment 生成器)。统一成 `transcribe(path, language=...)`
    返回 `{'text': ...}`,调用方就不用知道底下装的是哪个。
    """

    def __init__(self, name: str):
        from faster_whisper import WhisperModel
        kwargs = {'device': 'cpu', 'compute_type': _WHISPER_COMPUTE}
        # 已经有本地模型就直接用目录,别再去连 HF
        # (国内连 HF 只有 30KB/s,模型 138MB 能下一小时)
        local = os.path.join(_WHISPER_CACHE, name) if _WHISPER_CACHE else ''
        if local and os.path.isdir(local) and os.path.exists(
                os.path.join(local, 'model.bin')):
            logger.info('使用本地 ASR 模型: %s', local)
            self.model = WhisperModel(local, **kwargs)
            return
        if _WHISPER_CACHE:
            kwargs['download_root'] = _WHISPER_CACHE
        self.model = WhisperModel(name, **kwargs)

    def transcribe(self, path, language='en', fp16=False):
        segments, _info = self.model.transcribe(
            path,
            language=language,
            beam_size=_WHISPER_BEAM,
            # 孩子录音前后常有静音和杂音,先切掉
            vad_filter=True,
            vad_parameters={'min_silence_duration_ms': 500},
        )
        # faster-whisper 的 segment.text 自带前导空格,直接用 ' '.join
        # 会拼出双空格,词级比对就会多出「空词」。这里压平。
        raw = ''.join(s.text for s in segments)
        text = ' '.join(raw.split())
        return {'text': text}


def _load_asr():
    """按后端偏好加载 ASR 模型。失败抛 RuntimeError 让上层降级。

    任何「装好了但用不了」的情况(缓存损坏、av 版本不兼容、模型文件不全)
    都必须变成 RuntimeError —— 上层只认这个,会给孩子回一个「语音识别
    暂时不可用」,而不是 500 白屏。
    """
    backend = _WHISPER_BACKEND
    if backend in ('auto', 'faster'):
        try:
            return _FasterWhisperAdapter(_WHISPER_MODEL_NAME)
        except ImportError:
            if backend == 'faster':
                raise RuntimeError(
                    'faster-whisper 未安装。运行: pip install faster-whisper'
                )
            logger.info('faster-whisper 没装,退化到 openai-whisper')
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(
                f'语音识别模型加载失败: {type(e).__name__}: {e}'
            ) from e
    try:
        import whisper  # type: ignore
    except ImportError:
        raise RuntimeError(
            'ASR 没装。运行: pip install faster-whisper(推荐,省空间)'
            ' 或 pip install openai-whisper'
        )
    try:
        return whisper.load_model(_WHISPER_MODEL_NAME)
    except Exception as e:
        raise RuntimeError(
            f'语音识别模型加载失败: {type(e).__name__}: {e}'
        ) from e


def _get_whisper():
    """懒加载 ASR 模型。

    D2: 加锁防止并发首调 race。Lock 包整个 if+load,确保只 load 一次。
    后续命中缓存走 fast-path 不加锁 (Lock 自身开销几微秒,可忽略)。
    """
    global _ASR
    if _ASR is not None:
        return _ASR
    with _WHISPER_LOCK:
        if _ASR is not None:  # double-check:别的线程可能已经装好
            return _ASR
        t0 = time.monotonic()
        logger.info(f"加载 ASR 模型 {_WHISPER_MODEL_NAME} (后端 {_WHISPER_BACKEND}, 首次较慢)...")
        _ASR = _load_asr()
        logger.info(f"ASR 模型加载完成 took={int((time.monotonic() - t0) * 1000)}ms")
    return _ASR


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

    分词要**去掉标点**:转写里 "earthy." 和原句 "early" 比的是词,
    不是 "earthy." 和 "early" —— 否则界面上会显示「把 earthy. 读成 early」,
    那个句号是转写带出来的,不是孩子读错的一部分。
    和 phonemes.word_alignment 用同一套分词,两边的词才对得上。
    """
    sent_words = _WORD_RE.findall((sentence or '').lower())
    trans_words = _WORD_RE.findall((transcript or '').lower())
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


def _phoneme_tips(alignment: list) -> list:
    """给孩子的音素提示:「这个词里的 /f/ 还不太稳」。

    精确归因(能确定是哪个音)才给提示;粗粒度归因只说「这个词还不稳」——
    说不出是哪个音的时候别乱指。
    """
    from extensions import phonemes as _ph
    tips = []
    seen = set()
    for expected, got, is_error in (alignment or []):
        if not is_error or not expected:
            continue
        blamed, precise = _ph.blame_phonemes(expected, got or '')
        if not blamed:
            continue
        key = (expected, tuple(blamed))
        if key in seen:
            continue
        seen.add(key)
        item = {
            'word': expected,
            'heard': got or '',
            'phonemes': [],
            'precise': precise,
        }
        for p in blamed:
            info = _ph.phoneme_info(p)
            item['phonemes'].append({
                'id': info['id'], 'label': info['label'],
                'hint': info['hint'], 'vowel': info['vowel'],
            })
        tips.append(item)
        if len(tips) >= 5:
            break
    return tips


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
                asr_t0 = time.monotonic()
                asr_result = model.transcribe(tmp.name, language='en', fp16=False)
                transcript = (asr_result.get('text') or '').strip()
                logger.info(
                    f"ASR ok elapsed={int((time.monotonic() - asr_t0) * 1000)}ms "
                    f"transcript_len={len(transcript)}"
                )
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

        # === Step 3b: 下沉到音素层 ===
        # 词级差异只说「这个词读错了」,18254 个词没法练。
        # 归因到音素才知道是 /f/ 还是 /tʃ/ 不稳 —— 那才是能练的单位。
        # 图谱没灌数据时这一步自然什么都不做,不能拖垮反馈。
        phoneme_tips = []
        try:
            from extensions import phonemes as _ph
            alignment = _ph.word_alignment(sentence, transcript)
            _ph.record_alignment(alignment)
            phoneme_tips = _phoneme_tips(alignment)
        except Exception as e:
            logger.warning('音素归因失败(不影响反馈): %s', e)

        # === Step 4: LLM 生成反馈 ===
        try:
            llm_t0 = time.monotonic()
            client = get_llm_client()
            # R20: 拿孩子历史薄弱词喂进 prompt,让反馈个性化
            weak_words = get_weak_words(limit=10)
            prompt = _build_prompt(sentence, transcript, similarity, error_pairs, weak_words)
            feedback = client.chat_json(
                [{"role": "user", "content": prompt}],
                schema=FEEDBACK_JSON_SCHEMA,
            )
            logger.info(
                f"feedback ok elapsed={int((time.monotonic() - llm_t0) * 1000)}ms "
                f"similarity={similarity:.2f} weak_words={len(weak_words)}"
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
                "phoneme_tips": phoneme_tips,
            })

        return jsonify({
            "success": True,
            "transcript": transcript,
            "similarity": round(similarity, 2),
            "errors": [{"got": g, "expected": e, "tip": ""} for g, e in error_pairs],
            "feedback": feedback,
            "ai_unavailable": False,
            "phoneme_tips": phoneme_tips,
        })


def _rate_limited():
    ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'feedback')
    if not ok:
        return jsonify({
            "success": False,
            "error": f"请求过快, {retry} 秒后再试",
            "retryable": True,
            "retry_after": retry,
        }), 429
    return None