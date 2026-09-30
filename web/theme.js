/**
 * theme.js (R17) — 主题切换
 *
 * 三种模式:
 *   day   - 浅色 (硬覆盖)
 *   night - 深色 (硬覆盖)
 *   auto  - 不设 data-theme,跟随 prefers-color-scheme (默认)
 *
 * 持久化: localStorage.shTheme ∈ {day, night, auto}
 * 实际生效: document.documentElement.dataset.theme ∈ {light, dark} | (空)
 *   - 'day'  → dataset.theme = 'light'  → 强制浅色
 *   - 'night'→ dataset.theme = 'dark'   → 强制深色
 *   - 'auto'→ 移除 dataset.theme        → CSS 走 prefers-color-scheme
 *
 * 切换: cycleTheme() day → night → auto → day,图标 ☀/☾/◐
 */

(function () {
    'use strict';

    var STORAGE_KEY = 'shTheme';
    var VALID_MODES = ['day', 'night', 'auto'];
    var ICONS = { day: '☀', night: '☾', auto: '◐' };
    var TITLES = { day: '日间模式', night: '夜间模式', auto: '跟随系统' };

    function apply(mode) {
        var root = document.documentElement;
        if (mode === 'day') {
            root.dataset.theme = 'light';
        } else if (mode === 'night') {
            root.dataset.theme = 'dark';
        } else {
            // 'auto' 或未知: 删除属性,让 @media (prefers-color-scheme) 接管
            delete root.dataset.theme;
        }
        updateBtn(mode);
    }

    function getStored() {
        var m = localStorage.getItem(STORAGE_KEY);
        return VALID_MODES.indexOf(m) >= 0 ? m : 'auto';
    }

    function setStored(mode) {
        if (mode === 'auto') {
            localStorage.removeItem(STORAGE_KEY);
        } else {
            localStorage.setItem(STORAGE_KEY, mode);
        }
    }

    function updateBtn(mode) {
        // 用 data-action 找而不是 getElementById —— grammar.html 有两个主题按钮,
        // 同 id 只会拿到第一个,另一个永远停在初始图标。
        document.querySelectorAll('[data-action="cycleTheme"]').forEach(function (b) {
            b.textContent = ICONS[mode] || ICONS.auto;
            b.title = TITLES[mode] || TITLES.auto;
            b.setAttribute('aria-label', TITLES[mode] || TITLES.auto);
        });
    }

    function cycleTheme() {
        var current = getStored();
        var idx = VALID_MODES.indexOf(current);
        var next = VALID_MODES[(idx + 1) % VALID_MODES.length];
        setStored(next);
        apply(next);
    }

    function init() {
        var m = getStored();
        apply(m);
        // auto 模式下,系统主题切换 → 重新 apply 以刷新按钮图标(实际 CSS 已经 responsive)
        var mq = window.matchMedia('(prefers-color-scheme: dark)');
        if (mq.addEventListener) {
            mq.addEventListener('change', function () {
                if (getStored() === 'auto') apply('auto');
            });
        }
    }

    window.cycleTheme = cycleTheme;
    window.setTheme = apply;
    window.getTheme = getStored;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
