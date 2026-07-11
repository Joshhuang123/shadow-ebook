/**
 * dispatcher.js (R16.x)
 *
 * Universal click router — replaces 127 内联 onclick 属性。
 *
 * HTML 约定:
 *   <button data-action="foo">                    → window.foo(buttonEl, ev)
 *   <button data-action="foo" data-arg="bar">     → window.foo('bar', buttonEl, ev)
 *   <button data-action="foo" data-arg2="42">     → window.foo('bar', 42, buttonEl, ev)
 *   <button data-action="foo" data-arg3="x">      → window.foo('bar', 42, 'x', buttonEl, ev)
 *
 * - 数字 / 布尔 / null 自动按 JS 字面量 coerce,字符串保持原样
 * - `this` 在 handler 里 = 触发元素的 [data-action] 祖先
 * - 最后一个参数永远是 event 对象
 *
 * Wrappers (放在文件底部)— 干掉原 onclick 里的 event.stopPropagation() / 复合语句:
 *   clickStopCacheAudio   → cacheBookAudio 但不冒泡
 *   clickStopDeleteBook   → deleteBook 但不冒泡
 *   clickTriggerImportFile→ 模拟点 #import-file
 *   clickRestartPractice  → closeGrammar + startPractice
 *   clickStopPropagate    → 只 stopPropagation,无业务
 */

(function () {
    'use strict';

    function coerce(s) {
        if (s === undefined) return undefined;
        if (s === '') return s;
        if (/^-?\d+(?:\.\d+)?$/.test(s)) return Number(s);
        if (s === 'true') return true;
        if (s === 'false') return false;
        if (s === 'null') return null;
        return s;
    }

    function buildArgs(el, ev) {
        var ds = el.dataset;
        var args = [];
        if ('arg' in ds)  args.push(coerce(ds.arg));
        if ('arg2' in ds) args.push(coerce(ds.arg2));
        if ('arg3' in ds) args.push(coerce(ds.arg3));
        args.push(el);
        args.push(ev);
        return args;
    }

    function shouldIgnoreTarget(target) {
        if (!target) return false;
        if (target.isContentEditable) return true;
        var tag = target.tagName;
        if (tag === 'TEXTAREA') return true;
        if (tag === 'INPUT') {
            var t = (target.type || '').toLowerCase();
            // 按钮类 / 选择类的 input 点击是 OK 的
            if (t === 'button' || t === 'submit' || t === 'checkbox' ||
                t === 'radio' || t === 'file') return false;
            return true;  // text/password/email 等输入中
        }
        return false;
    }

    document.addEventListener('click', function (ev) {
        if (shouldIgnoreTarget(ev.target)) return;

        // 找最近的 [data-action] 祖先 — 这样图标在 button 里点击图标也行
        var el = ev.target.closest('[data-action]');
        if (!el || !el.dataset.action) return;

        var action = el.dataset.action;
        var fn = window[action];
        if (typeof fn !== 'function') {
            console.warn('[dispatcher] handler not found:', action, el);
            return;
        }

        // 原 onclick 也是 handler 跑完默认行为继续 — 不在这里 preventDefault
        fn.apply(el, buildArgs(el, ev));
    }, false);

    // ====== Wrappers for stopPropagation / composite actions ======

    window.clickStopCacheAudio = function (bid, el, ev) {
        if (ev && ev.stopPropagation) ev.stopPropagation();
        return window.cacheBookAudio && window.cacheBookAudio(bid);
    };

    window.clickStopDeleteBook = function (bid, btitle, el, ev) {
        if (ev && ev.stopPropagation) ev.stopPropagation();
        return window.deleteBook && window.deleteBook(bid, btitle);
    };

    window.clickStopCacheBookAudio = window.clickStopCacheAudio; // 兼容 (旧名)

    window.clickTriggerImportFile = function (el, ev) {
        var input = document.getElementById('import-file');
        if (input) input.click();
    };

    window.clickRestartPractice = function (key, el, ev) {
        if (window.closeGrammar) window.closeGrammar();
        if (window.startPractice) window.startPractice(key);
    };

    window.clickStopPropagate = function (el, ev) {
        if (ev && ev.stopPropagation) ev.stopPropagation();
    };

    // window.location.href 跳转
    window.clickGoHref = function (href, el, ev) {
        window.location.href = href;
    };
})();
