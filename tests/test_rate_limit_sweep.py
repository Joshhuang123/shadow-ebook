"""限流字典的过期清理 (_sweep_stale_api_rate)。

问题: `_api_rate_limit_ok` 只在某个 key 被再次访问时裁剪它自己的时间戳数组,
从不过期删除整个 key。平板换 WiFi、DHCP 换 IP、设备上下线,都会在 _API_RATE
里留下永久条目 —— 长期跑是个慢性的内存泄漏。

最重要的一条约束: 各 bucket 的 window 差很多 (`import` 是 3600s,其余 60s)。
如果实现里图省事用「全局最小 window」或「硬编码 60」去判断过期,
会把 `import` bucket 还没过期但暂时没被访问的 key 提前删掉 ——
结果是那个 IP 的上传限流被绕过 (10 次/小时的闸门形同虚设)。

这些测试现在会失败 —— 它们是给 _sweep_stale_api_rate 的实现当验收标准的。
实现完直接 `pytest tests/test_rate_limit_sweep.py` 即可。
"""
import pytest

from extensions import auth


@pytest.fixture(autouse=True)
def clean_rate_state():
    """每个测试前后都清空 _API_RATE,避免互相污染。"""
    auth._API_RATE.clear()
    yield
    auth._API_RATE.clear()


def seed(bucket, ip, timestamps):
    """往 _API_RATE 里塞一条记录,绕过 _api_rate_limit_ok 的限流判断。"""
    auth._API_RATE[(ip, bucket)] = list(timestamps)


# === 阈值行为 ===

def test_default_threshold_is_512():
    """阈值常量存在且是 512 —— 太小的值会让每个请求都全表遍历。"""
    assert auth._SWEEP_THRESHOLD == 512


def test_below_threshold_does_not_sweep(monkeypatch):
    """未超阈值时直接返回 0,一个 key 都不动 (包括早就过期的)。

    这是性能护栏: 如果每次请求都遍历全表,限流本身就变成了 DoS 放大点。
    """
    monkeypatch.setattr(auth, '_SWEEP_THRESHOLD', 512)
    seed('tts', '10.0.0.1', [0.0])  # 早该过期了,但没超阈值就不该被扫
    auth._API_RATE[('10.0.0.2', 'tts')] = [0.0]

    removed = auth._sweep_stale_api_rate(now=100_000.0)

    assert removed == 0
    assert len(auth._API_RATE) == 2, "未超阈值时不应删除任何 key"


def test_at_or_above_threshold_sweeps(monkeypatch):
    """达到阈值就该真扫,过期 key 被清掉。"""
    monkeypatch.setattr(auth, '_SWEEP_THRESHOLD', 3)
    seed('tts', '10.0.0.1', [0.0])        # 远超 60s 窗口 → 该删
    seed('tts', '10.0.0.2', [99_990.0])   # 10s 前,窗口内 → 该留
    seed('tts', '10.0.0.3', [0.0])        # 该删

    removed = auth._sweep_stale_api_rate(now=100_000.0)

    assert removed == 2
    assert ('10.0.0.1', 'tts') not in auth._API_RATE
    assert ('10.0.0.3', 'tts') not in auth._API_RATE
    assert ('10.0.0.2', 'tts') in auth._API_RATE


# === 核心陷阱: 必须按 bucket 各自的 window 判过期 ===

def test_long_window_bucket_not_evicted_early(monkeypatch):
    """`import` 桶窗口 3600s。100 秒前的请求对 60s 桶算过期,
    对 import 桶还很新鲜 —— 绝不能删,否则 IP 的上传限流被绕过。
    """
    monkeypatch.setattr(auth, '_SWEEP_THRESHOLD', 1)
    now = 1_000_000.0
    seed('import', '10.0.0.1', [now - 100])  # 100s 前,窗口 3600s → 保留

    removed = auth._sweep_stale_api_rate(now=now)

    assert removed == 0, "import 桶(3600s 窗口)不该被当成 60s 桶淘汰"
    assert ('10.0.0.1', 'import') in auth._API_RATE


def test_long_window_bucket_eventually_expires(monkeypatch):
    """对照组: import 桶真的超过 3600s 之后,还是应该被删掉的。
    证明上一条不是因为实现压根不碰 import 桶。"""
    monkeypatch.setattr(auth, '_SWEEP_THRESHOLD', 1)
    now = 1_000_000.0
    seed('import', '10.0.0.1', [now - 3601])

    removed = auth._sweep_stale_api_rate(now=now)

    assert removed == 1
    assert ('10.0.0.1', 'import') not in auth._API_RATE


def test_unknown_bucket_falls_back_to_global_window(monkeypatch):
    """未知 bucket 名退回 'global' 的 60s 窗口,而不是 KeyError 崩在请求线程里。"""
    monkeypatch.setattr(auth, '_SWEEP_THRESHOLD', 1)
    now = 1_000_000.0
    seed('不存在的桶', '10.0.0.1', [now - 100])   # 超过 global 的 60s → 该删
    seed('不存在的桶', '10.0.0.2', [now - 10])    # 窗口内 → 该留

    removed = auth._sweep_stale_api_rate(now=now)

    assert removed == 1
    assert ('10.0.0.1', '不存在的桶') not in auth._API_RATE
    assert ('10.0.0.2', '不存在的桶') in auth._API_RATE


# === 部分过期的 key: 保留 key,只裁剪陈旧时间戳 ===

def test_partially_expired_key_keeps_fresh_timestamps(monkeypatch):
    """窗口内还有请求的 key 不能整个删掉 —— 删了等于给这个 IP 重置配额。"""
    monkeypatch.setattr(auth, '_SWEEP_THRESHOLD', 1)
    now = 1_000_000.0
    seed('tts', '10.0.0.1', [now - 5000, now - 10])  # 一条过期一条新鲜

    removed = auth._sweep_stale_api_rate(now=now)

    assert removed == 0
    assert auth._API_RATE[('10.0.0.1', 'tts')] == [now - 10], \
        "陈旧时间戳应被剔除,但窗口内的那条要留下继续参与限流计数"


def test_empty_key_removed(monkeypatch):
    """全部时间戳都过期的 key 应该整个 pop 掉,不能留空数组占位。"""
    monkeypatch.setattr(auth, '_SWEEP_THRESHOLD', 1)
    now = 1_000_000.0
    seed('tts', '10.0.0.1', [now - 5000, now - 4000])

    removed = auth._sweep_stale_api_rate(now=now)

    assert removed == 1
    assert ('10.0.0.1', 'tts') not in auth._API_RATE


# === 边界与实现陷阱 ===

def test_does_not_mutate_dict_during_iteration(monkeypatch):
    """遍历中直接 del 字典会 RuntimeError: dictionary changed size during iteration。

    这个测试不 mock 任何东西,直接跑 —— 如果实现里边遍历边改 dict,这里会炸。
    """
    monkeypatch.setattr(auth, '_SWEEP_THRESHOLD', 1)
    now = 1_000_000.0
    for i in range(50):
        seed('tts', f'10.0.0.{i}', [now - 5000])       # 全该删
        seed('sync', f'10.0.1.{i}', [now - 5000])

    removed = auth._sweep_stale_api_rate(now=now)

    assert removed == 100
    assert auth._API_RATE == {}


def test_empty_dict_is_noop():
    """空 dict 不能崩(第一次请求就是这种情况)。"""
    assert auth._sweep_stale_api_rate(now=1_000_000.0) == 0


def test_sweep_runs_on_normal_request_path():
    """确认 _api_rate_limit_ok 真的会调用 sweep —— 防止实现了但没接上。"""
    import inspect
    src = inspect.getsource(auth._api_rate_limit_ok)
    assert '_sweep_stale_api_rate' in src, \
        "_api_rate_limit_ok 里没调用 sweep,实现了也不会生效"
