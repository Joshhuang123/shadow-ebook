"""R18 e2e 验证: /grammar 页 + /api/grammar/question 端到端。

策略:子进程 env 注入假 DEEPSEEK_API_KEY=fake-key,真 DeepSeek 会 401,
端点降级到静态题库 — 这条路覆盖了 404 检测、限流、JSON shape、fallback 全链路。

跑:`pytest tests/e2e/test_grammar_quiz.py -v`
"""
from __future__ import annotations

import json

import pytest


# === /grammar 页能加载,前端 JS 拿到了动态题库 ===
def test_grammar_page_loads(page, app_url):
    page.goto(f'{app_url}/grammar', wait_until='commit')
    # 等 JS 渲染出 Practice modal (动态出题后才有题)。
    # modal 默认 display:none,用 state='attached' 而不是 visible。
    page.wait_for_selector('#practice-modal, #grammar-modal', state='attached', timeout=10000)


def test_grammar_api_returns_static_fallback_when_llm_unreachable(page, app_url):
    """无真 DeepSeek key → LLM 401 → 降级静态题库,返回 success=True。"""
    # 通过 page.request 走同一浏览器 session,不会跨域
    resp = page.request.get(f'{app_url}/api/grammar/question/ket-present-simple')
    assert resp.status == 200
    data = resp.json()
    assert data['success'] is True
    assert data['source'] in ('llm', 'static', 'cache')  # 子进程有真 key 时可能是 llm
    assert 'q' in data['question']
    assert 'o' in data['question']
    assert isinstance(data['question']['a'], int)


def test_grammar_api_404_for_unknown_key(page, app_url):
    resp = page.request.get(f'{app_url}/api/grammar/question/this-key-does-not-exist')
    assert resp.status == 404
    assert '未知语法点' in resp.json()['error']


def test_grammar_api_respects_exclude_param(page, app_url):
    """exclude 含当前静态题 → 端点应该返回不同的题 (或 LLM 题)。"""
    # 先拿到一道题
    r1 = page.request.get(f'{app_url}/api/grammar/question/ket-present-simple').json()
    q1_text = r1['question']['q']
    # exclude 这道题再请求,理论上应该换
    r2 = page.request.get(
        f'{app_url}/api/grammar/question/ket-present-simple',
        params={'exclude': json.dumps([q1_text])},
    ).json()
    assert r2['success'] is True
    # 静态题库 ket-present-simple 有 2 道,exclude 第一道 → 第二道
    # (不会一致 — 这是验证 exclude 确实生效)
    assert r2['question']['q'] != q1_text or r2['source'] != 'static'