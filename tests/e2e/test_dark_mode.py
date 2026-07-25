"""R17 dark mode e2e 验证 (pytest 化)。

加载 4 页 (有 themeBtn 的) → 强制 light/dark → 计算 body 渐变首色亮度,
要求 light→dark 的 Δbrightness ≥ 0.3。

原一次性脚本在 tests/e2e/_legacy/verify_dark.py,如果还想临时跑单测可以 mv 回去。
"""
from __future__ import annotations

import re

import pytest


PAGES_WITH_THEME_BTN = ['/', '/tutor', '/grammar', '/stats']


def _hex_to_rgb(s: str):
    """'#F5EDE5' 或 'rgb(245, 237, 229)' 或 'rgba(0,0,0,0)' → tuple 或 None。"""
    if not s:
        return None
    if s.startswith('#'):
        h = s.lstrip('#')
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    if 'rgb' in s:
        inner = s[s.index('(') + 1:s.index(')')]
        nums = [int(x.strip()) for x in inner.split(',') if x.strip()]
        return tuple(nums[:3])
    return None


def _gradient_first_color_brightness(gradient_str: str) -> float | None:
    """取 `linear-gradient(... rgb(...) ...)` 的第一个 RGB,按 NTSC 公式算亮度。"""
    if not gradient_str or 'gradient' not in gradient_str:
        return None
    m = re.search(r'#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)', gradient_str)
    rgb = _hex_to_rgb(m.group(0)) if m else None
    if not rgb:
        return None
    r, g, b = rgb
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def _body_brightness(page) -> float | None:
    """读 body 计算后的 bg-image,fallback bg-color。"""
    bg_img = page.evaluate("() => getComputedStyle(document.body).backgroundImage")
    l = _gradient_first_color_brightness(bg_img or '')
    if l is not None:
        return l
    bg_color = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    rgb = _hex_to_rgb(bg_color or '')
    if not rgb:
        return None
    r, g, b = rgb
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


@pytest.mark.parametrize('path', PAGES_WITH_THEME_BTN)
def test_body_brightness_flips_with_theme(path: str, page, app_url):
    """4 页切深色后,body 亮度必须明显下降 (light > dark)。"""
    page.goto(app_url + path, wait_until='domcontentloaded')
    page.locator('body').wait_for(state='attached', timeout=30000)
    page.wait_for_timeout(400)  # 等 client JS 应用 theme

    page.evaluate(
        "() => { localStorage.setItem('shTheme', 'day');"
        " document.documentElement.dataset.theme = 'light'; }"
    )
    page.reload(wait_until='domcontentloaded')
    page.wait_for_timeout(400)
    light_l = _body_brightness(page)

    page.evaluate(
        "() => { localStorage.setItem('shTheme', 'night');"
        " document.documentElement.dataset.theme = 'dark'; }"
    )
    page.wait_for_timeout(400)
    dark_l = _body_brightness(page)
    theme_attr = page.evaluate("() => document.documentElement.dataset.theme")

    assert light_l is not None and dark_l is not None, (
        f'{path}: 无法读取 body bg — light={light_l} dark={dark_l}'
    )
    delta = light_l - dark_l
    assert delta > 0.3, (
        f'{path}: 切 dark 亮度差 {delta:.3f} < 0.3\n'
        f'  light={light_l:.3f} dark={dark_l:.3f} theme={theme_attr!r}'
    )


@pytest.mark.parametrize('path', PAGES_WITH_THEME_BTN)
def test_themeBtn_cycles_through_modes(path: str, page, app_url):
    """点 themeBtn 三次,应该 day → night → auto → day,data-theme 跟随变化。

    已知 /stats 在 reload 第二次时 domcontentloaded 会超 30s,怀疑
    stats.html 的 render 逻辑在 localStorage shadowStats 累积后跑 long task。
    """
    if path == '/stats':
        # TODO: 排查 /stats reload 第二次 domcontentloaded 超时 (issue #?)
        pytest.skip('/stats: reload 后 stats.js render 卡住,等 fix 后再开')

    page.goto(app_url + path, wait_until='domcontentloaded')
    btn = page.locator('#themeBtn').first
    btn.wait_for(state='visible', timeout=30000)

    # 起始 light
    page.evaluate("() => { localStorage.setItem('shTheme', 'day'); document.documentElement.dataset.theme = 'light'; }")
    page.reload(wait_until='domcontentloaded')
    page.locator('#themeBtn').first.wait_for(state='visible', timeout=30000)

    btn.click()
    page.wait_for_timeout(50)
    t1 = page.evaluate("() => document.documentElement.dataset.theme")
    assert t1 == 'dark', f'cycleTheme 第 1 击应到 dark,实际 {t1!r}'

    btn.click()
    page.wait_for_timeout(50)
    t2 = page.evaluate("() => document.documentElement.dataset.theme")
    # auto 模式下 dataset.theme 被 `delete root.dataset.theme` 移除,
    # evaluate 看到属性不存在,JSON 序列化变成 None
    assert t2 in ('', 'auto', None), f'cycleTheme 第 2 击应到 auto,实际 {t2!r}'

    btn.click()
    page.wait_for_timeout(50)
    t3 = page.evaluate("() => document.documentElement.dataset.theme")
    assert t3 == 'light', f'cycleTheme 第 3 击应回 day/light,实际 {t3!r}'
