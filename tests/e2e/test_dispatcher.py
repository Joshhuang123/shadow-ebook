"""data-action 路由 e2e 测试。

strategy:
1. 静态扫描 + 4 类 assertion
   - resolve: 所有 [data-action] 都对应 window 上一个函数
   - safe_click: SAFE_CLICKS 集合里的 action 点一下不抛异常
   - arg_parse: data-arg=数字 / 字符串能正确传到 handler
   - delegation: 点 [data-action] 元素的子节点也能 routing 到该元素
"""
from __future__ import annotations

import pytest


# 安全动作集合 — 点击后只切换 UI 状态,不会启动音频/录音/对话框业务流,
# 也不依赖具体书籍数据。Dispatcher 路由能不能跑通,就靠点这些元素检验。
#
# 决策参考:
#   ✓  UI 切换类     cycleTheme / setMode / changeFontSize
#                    toggleSidebar / toggleTocSidebar
#                    close*Modal (closeARPanel/closeCompModal/closeReviewModal/
#                                 closeWordModal/closeGrammar/closePractice)
#                    clickStopPropagate (无副作用 wrapper)
#   ✗  启动业务流    showARPanel / showComprehensionModal / showVocabReview /
#                    showBookList / showUnits / showBooks / showGrammar /
#                    showChangePwd / startRecording / startVocabTest / showARPanel
#                    — 这些需要具体数据准备态,放进正式 e2e 用例
#   ✗  音频播放      play* (依赖已加载音频/sentence 状态)
#   ✗  数据写        addToVocab / retestVocab / resetStats / exportData / resetData
SAFE_CLICKS: set[str] = {
    # UI 切换 / 折叠
    'cycleTheme', 'setMode', 'changeFontSize',
    'toggleSidebar', 'toggleTocSidebar',
    # modal 关闭
    'closeARPanel', 'closeCompModal', 'closeReviewModal',
    'closeWordModal', 'closeGrammar', 'closePractice',
    # 纯 forward-only wrapper
    'clickStopPropagate',
}


def test_resolve_all_routes(page, app_url):
    """4 个有 data-action 的页面,所有 [data-action] 都对应 window 函数。

    用例: 即便某个 handler 没被实际点击,也得在 window 上存在可调。
    """
    pages_with_actions = ['/', '/tutor', '/grammar', '/stats']
    for path in pages_with_actions:
        page.goto(app_url + path, wait_until='commit')
        page.locator('body').wait_for(state='attached', timeout=30000)
        page.wait_for_timeout(200)

        names = page.evaluate(
            "() => Array.from(document.querySelectorAll('[data-action]'))"
            ".map(el => el.dataset.action)"
        )
        assert names, f'{path} 没有 data-action 元素?'

        missing = [
            n for n in names
            if not page.evaluate("(a) => typeof window[a] === 'function'", n)
        ]
        assert not missing, (
            f'{path}: dispatcher 找不到 handler: {missing}\n'
            f'(共 {len(names)} 个 action, 定义于 web/js/dispatcher.js)'
        )


@pytest.mark.parametrize('action', sorted(SAFE_CLICKS)) if SAFE_CLICKS else []
def test_safe_click_dispatches(action: str, page, app_url):
    """对 SAFE_CLICKS 里每个 action,点第一个可见的 [data-action] 元素,不应报 pageerror。"""
    page.goto(app_url + '/', wait_until='commit')
    page.locator('body').wait_for(state='attached', timeout=30000)
    page.wait_for_timeout(300)

    # 先清 console 监听
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)

    # 找该 action 第一个能 click 的元素(可见 + pointer-events != none)
    clicked = page.evaluate("""(action) => {
        const el = [...document.querySelectorAll('[data-action]')]
            .find(e => e.dataset.action === action
                     && e.offsetParent !== null
                     && getComputedStyle(e).pointerEvents !== 'none');
        if (!el) return null;
        const box = el.getBoundingClientRect();
        return { tag: el.tagName, rect: [box.x, box.y, box.width, box.height] };
    }""", action)

    if not clicked:
        pytest.skip(f'/{action}: 没找到可见的 [data-action={action}]')

    page.locator(f'[data-action="{action}"]').first.click(force=True)
    page.wait_for_timeout(150)

    assert not errors, f'click {action} 抛错: {errors}'


def test_arg_parsing_numeric(page, app_url):
    """data-arg=-2 (数字字面量) 应被 dispatcher coerce 成数字传到 handler。

    changeFontSize 是为数不多 data-arg=数字且点击立刻反映在 DOM 的 action。
    """
    page.goto(app_url + '/', wait_until='commit')
    page.locator('body').wait_for(state='attached', timeout=30000)
    page.wait_for_timeout(300)

    # 取点击前的字号数据 (存在 localStorage 里)
    before = page.evaluate("() => parseFloat(localStorage.getItem('shFontSize') || '16')")

    page.locator('[data-action="changeFontSize"][data-arg="-2"]').first.click()
    page.wait_for_timeout(100)

    after = page.evaluate("() => parseFloat(localStorage.getItem('shFontSize') || '16')")
    assert after < before, f'changeFontSize(-2) 没缩字号:before={before} after={after}'


def test_dispatch_via_child_element(page, app_url):
    """点击 [data-action] 的子元素 (例 button 里的图标) 也应 routing 到 button。

    验证 closest('[data-action]') 的逻辑 — R16.x 从 127 个 onclick 迁移时这个行为要稳。
    """
    page.goto(app_url + '/', wait_until='commit')
    page.locator('body').wait_for(state='attached', timeout=30000)
    page.wait_for_timeout(300)

    # themeBtn 是个 button 带文字 '日'/'☾' — 点文字节点
    rect = page.evaluate("() => { const b = document.getElementById('themeBtn'); const r = b.getBoundingClientRect(); return [r.x + 2, r.y + 2]; }")
    theme_before = page.evaluate("() => document.documentElement.dataset.theme || 'auto'")
    page.mouse.click(rect[0], rect[1])
    page.wait_for_timeout(200)
    theme_after = page.evaluate("() => document.documentElement.dataset.theme || 'auto'")
    assert theme_before != theme_after, (
        f'点 themeBtn 内部子元素没切换主题: before={theme_before} after={theme_after}'
    )
