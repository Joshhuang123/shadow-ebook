"""R19 e2e 验证: /tutor 页 + /api/recording/feedback 端到端。

策略:不依赖真 whisper (CI 装 200MB 模型太重),只验证:
1. /tutor 页能加载,前端 JS 有录音 + feedback 流程
2. 端点对缺参数返回 400
3. 端点对真音频文件 → 503 (whisper 未装) 或 200/502 (装了)

跑:`pytest tests/e2e/test_tutor_feedback.py -v`
"""
from __future__ import annotations

import io

import pytest


def test_tutor_page_loads(page, app_url):
    page.goto(f'{app_url}/tutor', wait_until='commit')
    # 至少要看到句子卡片的容器 — sentence-display 默认 display:none,用 attached
    page.wait_for_selector('#sentence-text, .sentence-display', state='attached', timeout=10000)


def test_feedback_api_rejects_missing_audio(page, app_url):
    """没传 audio → 400。"""
    resp = page.request.post(
        f'{app_url}/api/recording/feedback',
        multipart={'sentence': 'hello'},
    )
    assert resp.status == 400
    data = resp.json()
    assert data['success'] is False
    assert 'audio' in data['error'] or 'sentence' in data['error']


def test_feedback_api_rejects_missing_sentence(page, app_url):
    """没传 sentence → 400。"""
    resp = page.request.post(
        f'{app_url}/api/recording/feedback',
        multipart={
            'audio': {
                'name': 'rec.webm',
                'mimeType': 'audio/webm',
                'buffer': b'\x1a\x45\xdf\xa3' + b'\x00' * 50,
            },
        },
    )
    assert resp.status == 400


def test_feedback_api_handles_audio_without_whisper(page, app_url):
    """传了音频但 whisper 未装 → 503 (asr_available=False)。装了 → 200 或 502。

    这个测试不管 whisper 装没装都不该崩,只是断言行为合理。
    """
    resp = page.request.post(
        f'{app_url}/api/recording/feedback',
        multipart={
            'audio': {
                'name': 'rec.webm',
                'mimeType': 'audio/webm',
                'buffer': b'\x1a\x45\xdf\xa3' + b'\x00' * 50,
            },
            'sentence': 'What are you doing?',
        },
    )
    # 装 whisper → 200 (success, 但 transcript 可能是空/转写失败) 或 502 (ffmpeg error)
    # 没装 → 503 (asr_available=False)
    assert resp.status in (200, 502, 503), f"unexpected status: {resp.status} body={resp.text}"
    data = resp.json()
    if resp.status == 503:
        assert data.get('asr_available') is False
        assert 'whisper' in data['error'].lower()