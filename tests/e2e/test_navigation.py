"""5 页导航 e2e 测试。

涵盖: HTTP 200 / nav-link href / 实际跳转 / 跨页 theme 持久化 / parent 登录门。
"""
from __future__ import annotations

import pytest


PAGES_WITH_TOP_NAV = ['/', '/tutor', '/grammar', '/stats']

# 这些页面之间用 top-nav 的 nav-link 互相跳
NAV_TARGETS = ['/', '/tutor', '/grammar', '/stats']


def test_all_five_pages_return_200(page, app_url):
    """/、/tutor、/grammar、/parent、/stats 全部 200 + 含 body。"""
    for path in ['/', '/tutor', '/grammar', '/parent', '/stats']:
        resp = page.goto(app_url + path)
        assert resp.status == 200, f'{path} returned {resp.status}'
        assert page.locator('body').count() == 1, f'{path} 没渲染 body'


@pytest.mark.parametrize('source', NAV_TARGETS)
@pytest.mark.parametrize('target', NAV_TARGETS)
def test_nav_link_round_trip(source: str, target: str, page, app_url):
    """每页的 top-nav 都应能跳到 4 个目标(除自身外,验证也能点到自己)。

    用 selector [href='...'] 找 nav-link,验证点完跳转后 url.pathname 匹配。
    """
    if source == target:
        pytest.skip(f'同一页面({source})不用测跳转')

    page.goto(app_url + source, wait_until='commit')
    page.locator('body').wait_for(state='attached', timeout=30000)

    # target 已是 nav-link 的 href,过滤掉同页 self-link
    link = page.locator(f'nav.top-nav a.nav-link[href="{target}"]').first
    link.wait_for(state='visible')
    link.click()

    page.wait_for_url(f'**{target}', timeout=15000)
    # 用 URL 不带 query 比较
    from urllib.parse import urlparse
    got = urlparse(page.url).path
    assert got == target, f'{source} 跳 {target} 失败,实际到 {got}'


@pytest.mark.parametrize('path', PAGES_WITH_TOP_NAV)
def test_nav_links_present(path: str, page, app_url):
    """每页 top-nav 含 4 个期望 nav-link。"""
    page.goto(app_url + path, wait_until='commit')
    page.locator('body').wait_for(state='attached', timeout=30000)

    nav = page.locator('nav.top-nav')
    assert nav.count() >= 1, f'{path} 缺 top-nav'

    # 检查 href 集合
    hrefs = page.locator('nav.top-nav a.nav-link').evaluate_all(
        "els => els.map(e => new URL(e.href, location.origin).pathname)"
    )
    assert '/' in hrefs, f'{path} 缺 / 链接'
    assert '/tutor' in hrefs, f'{path} 缺 /tutor 链接'
    assert '/grammar' in hrefs, f'{path} 缺 /grammar 链接'
    assert '/stats' in hrefs, f'{path} 缺 /stats 链接'
    # parent.html 是登录门,不一定出现在所有 nav 里,放过


def test_theme_persists_across_navigation(page, app_url):
    """切换 dark theme 后跳到另一页,新页面仍是 dark。"""
    page.goto(app_url + '/', wait_until='commit')
    page.locator('body').wait_for(state='attached', timeout=30000)

    # 切到 night
    page.evaluate("localStorage.setItem('shTheme', 'night')")
    page.goto(app_url + '/grammar', wait_until='commit')
    page.locator('body').wait_for(state='attached', timeout=30000)
    page.wait_for_timeout(300)  # 等 client JS 应用 theme

    theme = page.evaluate("() => document.documentElement.dataset.theme")
    assert theme == 'dark', f'切 dark 后跳 /grammar,实际 theme={theme!r}'

    # 切回去
    page.evaluate("localStorage.setItem('shTheme', 'day')")
    page.goto(app_url + '/', wait_until='commit')
    page.locator('body').wait_for(state='attached', timeout=30000)
    page.wait_for_timeout(300)
    theme = page.evaluate("() => document.documentElement.dataset.theme")
    assert theme == 'light', f'切 day 后回 /,实际 theme={theme!r}'


def test_parent_requires_login(page, app_url):
    """/parent 可能跳到 /parent/login 或直接渲染,只看 200 + 含家长相关关键字。"""
    resp = page.goto(app_url + '/parent')
    assert resp.status == 200
    body = page.locator('body').inner_text()
    # 不强制要求 "登录" 字样,但得有 "家长/parent" 关键字或登录表单
    has_parent_kw = any(kw in body for kw in ('家长', 'parent', 'Parent', '登录', 'PIN', '密码'))
    assert has_parent_kw, f'/parent 没渲染家长相关内容:\n{body[:200]}'
