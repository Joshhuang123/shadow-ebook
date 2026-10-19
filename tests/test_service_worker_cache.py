"""Service Worker 缓存策略守护。

这里守的是 2026-10-19 真实踩过的两个坑,都不是理论风险:

1) **/api/ 曾经被缓存** —— 结果某个浏览器 profile 的缓存里存了一份坏掉的
   /api/book/<id> 响应,点「继续读」时请求根本没到服务器(服务端日志零记录),
   前端拿到 success 不为真的数据后**静默什么都不做**。用户只看到「点了没反应」。
   /api/ 下全是可变状态(阅读进度、统计、孩子档案),缓存它们本来就不对。

2) **静态资源曾经是缓存优先** —— 改了 CSS 刷新页面看到的还是旧的,
   很容易误判成「改错了」。

这些都是「谁都不会再主动去想」的隐性契约,删掉一行就静默回归,所以写成测试钉住。
"""
from pathlib import Path
import re
import pytest

SW = Path(__file__).resolve().parent.parent / 'web' / 'service-worker.js'


@pytest.fixture(scope='module')
def src():
    return SW.read_text(encoding='utf-8')


def _branch(src: str, marker: str) -> str:
    """截出某个顶层分支的源码,用于只在该分支内做断言。

    结束点取「下一个同级 if」或「fetch 监听器的收尾」,两者都是 2 空格缩进,
    不会误切到分支内部 4 空格缩进的 if。
    """
    i = src.index(marker)
    rest = src[i + len(marker):]
    ends = [p for p in (rest.find('\n  if ('), rest.find('\n});')) if p != -1]
    return rest[:min(ends)] if ends else rest


def test_sw_file_exists():
    assert SW.exists(), 'service-worker.js 不见了,PWA 直接失效'


def test_api_not_cached(src):
    """/api/ 分支里不允许出现任何 cache.put —— 缓存 API 就是本 bug 的根源。"""
    branch = _branch(src, "url.pathname.startsWith('/api/')")
    assert 'cache.put' not in branch, '/api/ 又开始写缓存了,阅读进度会读到陈旧值'


def test_api_has_no_cache_fallback(src):
    """/api/ 请求失败时不能拿缓存兜底,必须 reject 让前端弹错误。

    静默兜底 = 用户点了没反应还不知道为什么,这是最贵的一类故障。
    """
    branch = _branch(src, "url.pathname.startsWith('/api/')")
    assert 'caches.match' not in branch, '/api/ 又退回缓存兜底了,坏数据会悄悄顶上来'


def test_api_returns_explicit_error_when_offline(src):
    branch = _branch(src, "url.pathname.startsWith('/api/')")
    assert '503' in branch and 'offline' in branch, \
        '/api/ 断网时应该回一个明确的 success:false,而不是空响应'


def test_static_assets_network_first(src):
    """CSS/JS 必须网络优先、缓存兜底,不能是缓存优先。"""
    static_branch = _branch(src, '静态资源(CSS / JS)')
    fetch_at = static_branch.find('fetch(request)')
    fallback_at = static_branch.find('caches.match(request)')
    assert fetch_at != -1, '静态资源分支里没有网络请求'
    assert fallback_at != -1, '静态资源分支没有缓存兜底'
    assert fetch_at < fallback_at, \
        '静态资源变成缓存优先了 —— 改完 CSS 刷新会看不到效果(这个坑踩过不止一次)'


def test_sw_takes_over_immediately(src):
    """install 必须 skipWaiting、activate 必须 clients.claim。

    少任何一个,新版本都要等到用户把所有标签页关掉才生效 ——
    表现就是「我明明改了,刷新也没用」。
    """
    assert 'self.skipWaiting()' in src, 'install 里没有 skipWaiting,新版本 SW 会卡在 waiting'
    assert 'self.clients.claim()' in src, 'activate 里没有 clients.claim,新 SW 不会立刻接管'


def test_activate_deletes_old_caches(src):
    """换 CACHE_NAME 必须真的清掉旧缓存,否则坏缓存永远留在设备上。"""
    assert re.search(r"caches\.delete\(", src), 'activate 没有删除旧缓存'
    assert "startsWith('shadow-')" in src, '旧缓存清理没有限定自己的命名空间'


def test_cache_name_bumped(src):
    """改动本文件后必须把 CACHE_NAME +1。名字没变 = 设备上还是老缓存。"""
    assert re.search(r"const CACHE_NAME = 'shadow-ebook-v\d+'", src)
