"""
Owns: LLM client abstraction (BaseLLMClient + OpenAICompatClient) + provider factory.
       Chat and structured JSON outputs with jsonschema validation.
Does NOT own: feature-specific prompts or caching (grammar_quiz.py, future feedback.py).
"""
import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)


# === 抽象接口 ===
class BaseLLMClient:
    """所有 LLM client 必须实现的接口。

    chat()     -> 原始文本响应
    chat_json() -> 校验过的 JSON 对象 (默认实现:chat + json.loads + jsonschema 校验)
    """
    def chat(self, messages: list[dict], **kw) -> str:
        raise NotImplementedError

    def chat_json(self, messages: list[dict], schema: dict, **kw) -> dict:
        """默认实现走 chat + 强校验,子类可重写更高效的版本。"""
        raw = self.chat(messages, **kw)
        return _parse_and_validate(raw, schema)


# === Retry 配置 ===
# 瞬时错误(HTTP 5xx/408/429、网络错误)重试 1 次,4xx 不重试(用户/配置问题,重试无意义)。
# 退避 0.5s,够上游恢复也不至于让用户等太久(单次 chat 通常 2-5s)。
_RETRY_BACKOFF_S = 0.5
_RETRYABLE_HTTP_CODES = {408, 429, 500, 502, 503, 504}


def _urlopen_with_retry(req, timeout: float, max_retries: int = 1):
    """urlopen 包装:瞬时错误重试。返回 (response_or_None, last_error_str)。

    成功 → (resp, None);失败 → (None, "LLM upstream HTTP 500" 等)
    """
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout), None
        except urllib.error.HTTPError as e:
            err_body = e.read().decode(errors="replace")[:500]
            last_err = f"LLM upstream HTTP {e.code}: {err_body}"
            if e.code not in _RETRYABLE_HTTP_CODES or attempt >= max_retries:
                logger.warning(last_err)
                return None, last_err
            logger.info(f"LLM HTTP {e.code} 瞬时错误, {0.5 * (attempt + 1)}s 后重试...")
            time.sleep(_RETRY_BACKOFF_S * (attempt + 1))
        except urllib.error.URLError as e:
            last_err = f"LLM unreachable: {e.reason}"
            if attempt >= max_retries:
                logger.warning(last_err)
                return None, last_err
            logger.info(f"LLM 网络错误, {0.5 * (attempt + 1)}s 后重试...")
            time.sleep(_RETRY_BACKOFF_S * (attempt + 1))
    return None, last_err or "LLM request failed"


# === OpenAI 兼容协议的通用实现 (DeepSeek / MiniMax / Moonshot / 智谱 全套这套) ===
class OpenAICompatClient(BaseLLMClient):
    def __init__(self, base_url: str, api_key: str, model: str,
                 default_temperature: float = 0.3, default_max_tokens: int = 500,
                 timeout: float = 30.0, extra_headers: Optional[dict] = None):
        if not api_key:
            raise RuntimeError(
                f"LLM api_key 未配置。检查对应环境变量(DeepSeek→DEEPSEEK_API_KEY 等)"
            )
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.model = model
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

    def chat(self, messages: list[dict], **kw) -> str:
        body = {
            "model": kw.get("model", self.model),
            "messages": messages,
            "temperature": kw.get("temperature", self.default_temperature),
            "max_tokens": kw.get("max_tokens", self.default_max_tokens),
        }
        if "response_format" in kw:
            body["response_format"] = kw["response_format"]

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                **self.extra_headers,
            },
            method="POST",
        )

        # === D4: 结构化日志 — 记耗时 + key ===
        t0 = time.monotonic()
        resp, err = _urlopen_with_retry(req, self.timeout)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if err:
            logger.info(f"LLM call failed model={self.model} elapsed={elapsed_ms}ms err={err[:120]}")
            raise RuntimeError(err)

        try:
            payload = json.loads(resp.read())
        except Exception as e:
            logger.info(f"LLM call failed model={self.model} elapsed={elapsed_ms}ms err=malformed JSON")
            raise RuntimeError(f"LLM returned malformed JSON: {e}") from e

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            logger.warning(f"LLM malformed response: {payload!r}")
            raise RuntimeError("LLM returned malformed response") from e

        usage = payload.get("usage", {})
        logger.info(
            f"LLM call ok model={self.model} elapsed={elapsed_ms}ms "
            f"prompt_tokens={usage.get('prompt_tokens', '?')} "
            f"completion_tokens={usage.get('completion_tokens', '?')}"
        )
        return content


# === Provider 子类 — 只放默认值,override 模型名 / 限参 ===
class DeepSeekClient(OpenAICompatClient):
    def __init__(self, api_key: str, model: str = "deepseek-chat", **kw):
        super().__init__(
            base_url="https://api.deepseek.com/v1",
            api_key=api_key,
            model=model,
            default_temperature=kw.pop("temperature", 0.3),  # 出题要稳
            **kw,
        )


class MiniMaxClient(OpenAICompatClient):
    """MiniMax M 系列 (M3.1-Flash-Preview / M3 / M2.7) — OpenAI 兼容协议。

    端点:`api.minimax.cn/v1` (官方文档 2026-09)。M3.1 默认开启思考,
    `reasoning_content` 通过单独字段返回,我们只读 `content`(最终答案)。
    """
    DEFAULT_MODEL = "MiniMax-M3.1-Flash-Preview"

    def __init__(self, api_key: str, model: Optional[str] = None, **kw):
        super().__init__(
            base_url="https://api.minimax.cn/v1",
            api_key=api_key,
            model=model or self.DEFAULT_MODEL,
            **kw,
        )


# === JSON 校验工具 ===
def _parse_and_validate(raw: str, schema: dict) -> dict:
    """chat_json 默认实现:从 markdown code fence 里抠 JSON,跑 jsonschema 校验。

    LLM 经常把 JSON 裹在 ```json ... ``` 里,要剥掉再 parse。
    """
    text = raw.strip()
    # 剥 code fence
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LLM returned invalid JSON: {e}") from e

    try:
        import jsonschema
        jsonschema.validate(obj, schema)
    except ImportError:
        logger.warning("jsonschema 未装,跳过校验(建议装上)")
    except jsonschema.ValidationError as e:
        raise RuntimeError(f"LLM JSON schema mismatch: {e.message}") from e

    return obj


# === 工厂 ===
def get_llm_client() -> BaseLLMClient:
    """按 LLM_PROVIDER 环境变量选 client。LLM_MODEL 可覆盖默认模型名。

    加新 provider:在这里加一个分支就行,业务代码不用动。
    """
    provider = os.environ.get("LLM_PROVIDER", "deepseek").lower()

    if provider == "deepseek":
        return DeepSeekClient(
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            model=os.environ.get("LLM_MODEL", "deepseek-chat"),
        )
    if provider == "minimax":
        return MiniMaxClient(
            api_key=os.environ.get("MINIMAX_API_KEY", ""),
            model=os.environ.get("LLM_MODEL", MiniMaxClient.DEFAULT_MODEL),
        )

    raise RuntimeError(
        f"未知 LLM_PROVIDER={provider!r}。支持: deepseek, minimax"
    )