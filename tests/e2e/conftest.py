"""E2E 测试 fixture: session 级 Flask 子进程 + 共享 Chromium browser。

设计:
- session-scoped `app_url`: 启动一次 Flask 子进程,所有测试共用,避免每次启停
- session-scoped `browser`: 一个 Chromium 实例,所有 page 共享
- function-scoped `page`: 每个测试一个新 tab,默认加载 / (可自己 goto)
- pytest 默认会合并 tests/conftest.py 和 tests/e2e/conftest.py,后者优先
  (避免被 `tmp_db`/`clear_login_state` 那种 DB-fixture 影响)

为什么不用 pytest-playwright: 我们要测的是"自己起的 Flask 跑哪些路由",
不是它的 webserver fixture;sync_playwright + sync_launch 已经够轻。
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import Browser, sync_playwright

ROOT = Path(__file__).resolve().parent.parent.parent


def _find_free_port() -> int:
    """绑 0 让内核挑端口,避免 CI / 本地端口冲突。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _wait_ready(url: str, timeout_s: float = 9.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status < 500:
                    return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError(f'flask did not become ready within {timeout_s}s: {url}')


@pytest.fixture(scope='session')
def app_url() -> str:
    """启动 Flask 子进程,返回 base URL (例 http://127.0.0.1:55321)。

    ci 环境下不依赖 sandbox 端口分配,子进程从内核要一个空闲端口。
    """
    port = _find_free_port()
    env = os.environ.copy()
    env['FLASK_PORT'] = str(port)
    proc = subprocess.Popen(
        [sys.executable, '-c',
         f'import sys; sys.path.insert(0, "{ROOT}"); '
         f'from app import app; '
         f'import logging; logging.getLogger("werkzeug").setLevel(logging.WARNING); '
         f'app.run(host="127.0.0.1", port={port}, debug=False, use_reloader=False)'],
        cwd=str(ROOT),
        env=env,
    )
    base = f'http://127.0.0.1:{port}'
    try:
        _wait_ready(f'{base}/healthz')
    except Exception:
        proc.terminate()
        proc.wait(timeout=2)
        raise

    yield base

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope='session')
def browser() -> Browser:
    """共享的 Chromium 实例,session 级,close 在最后。

    launch args: 减少内存压力 + 防止跑 30+ e2e 后 chromium 累坏。
    dev-shm-usage 是 Linux 默认会占满 /dev/shm 的,mac 上无所谓但留着无害。

    D3: 优先用系统 Chrome (channel='chrome'),跳过 playwright 自带的
    chromium 下载 (~150MB,网速慢时容易卡)。Playwright 自带 chromium 装不上
    时 fallback 到 chrome,行为对前端测试无差别。
    """
    with sync_playwright() as pw:
        launch_args = [
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--no-sandbox',
        ]
        # 优先 channel=chrome (系统已装),省掉 150MB 下载
        try:
            b = pw.chromium.launch(channel='chrome', headless=True, args=launch_args)
        except Exception:
            # 回退到 playwright 自带 chromium
            b = pw.chromium.launch(headless=True, args=launch_args)
        yield b
        b.close()


@pytest.fixture
def page(browser: Browser, app_url: str):
    """新 tab (function scope),默认加载 / 并 wait idle。

    测试可以继续 page.goto(...) 跳别的路径。
    ci=true 时自动开 trace,失败时方便排查。

    known_console_noisy: 当前 HTML 还有遗留 inline `style="..."` 属性
    (`app.py` 的 CSP 已经 `style-src 'self'`),会在 console 喷
    "Applying inline style violates..."。R16.x 应该清干净(独立工作),
    这里先 filter 掉避免误伤其他测试。
    """
    ctx = browser.new_context()
    p = ctx.new_page()
    # /stats 初次渲染要算 streak/chart,可能 > 15s
    p.set_default_timeout(30000)

    console_errors: list[str] = []
    page_errors: list[str] = []

    def _on_console(m):
        if m.type != 'error':
            return
        t = m.text
        if 'Content Security Policy' in t and 'style-src' in t:
            return  # CSP inline-style 已知噪声,独立工程修
        console_errors.append(t)

    p.on('console', _on_console)
    p.on('pageerror', lambda e: page_errors.append(str(e)))

    # 默认加载 /,但只用 commit 等 response headers,不耗 'load' event —
    # 在跑 30+ e2e 后 Chromium 累,load event 触发慢;commit 立刻返
    p.goto(app_url + '/', wait_until='commit')

    yield p

    if page_errors or console_errors:
        sys.stderr.write(
            f'[e2e] page {p.url} had errors:\n'
            f'  pageerror: {page_errors}\n'
            f'  console error: {console_errors}\n'
        )

    ctx.close()
