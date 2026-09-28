"""
Owns: parent PIN-protected route decorator, login rate limiting, generic API rate limiting.
Does NOT own: PIN storage / verification (parent_data.py).
"""
import logging
import threading
from functools import wraps
import time
from flask import jsonify, session


logger = logging.getLogger(__name__)


# === 登录限流: 防 LAN 上暴力破解 4 位 PIN ===
_LOGIN_WINDOW = {}  # ip -> [timestamp, ...]
MAX_ATTEMPTS = 5
LOCKOUT_SEC = 900   # 锁定 15 分钟
_AUTH_LOCK = threading.Lock()  # 保护 _LOGIN_WINDOW (Phase 2 加锁)


def _login_rate_limit_ok(ip):
    """返回 (ok, retry_after_sec). 锁定时返回 (False, 至少 1 秒)"""
    with _AUTH_LOCK:
        now = time.time()
        arr = _LOGIN_WINDOW.get(ip, [])
        arr = [t for t in arr if now - t < LOCKOUT_SEC]
        if len(arr) >= MAX_ATTEMPTS:
            retry = int(LOCKOUT_SEC - (now - arr[0]))
            return False, max(retry, 1)
        _LOGIN_WINDOW[ip] = arr
        return True, 0


def _login_record_failure(ip):
    with _AUTH_LOCK:
        arr = _LOGIN_WINDOW.setdefault(ip, [])
        arr.append(time.time())


def _login_clear(ip):
    with _AUTH_LOCK:
        _LOGIN_WINDOW.pop(ip, None)


def _login_remaining(ip):
    """返回该 IP 还能试几次 (0 = 已锁定)。前端可显示 "还剩 N 次"。"""
    with _AUTH_LOCK:
        now = time.time()
        arr = [t for t in _LOGIN_WINDOW.get(ip, []) if now - t < LOCKOUT_SEC]
        return max(MAX_ATTEMPTS - len(arr), 0)


# === 通用 API 限流: per-IP 滑动窗口 ===
_API_RATE = {}  # (ip, bucket) -> [timestamp, ...]
_API_LIMITS = {
    'tts':         {'max': 30,  'window': 60},     # 防 TTS 缓存爆
    'sync':        {'max': 60,  'window': 60},     # 防 anon 上报刷数据
    'import':      {'max': 10,  'window': 3600},   # 防 100MB EPUB 上传被滥用
    'pregenerate': {'max': 10,  'window': 60},     # 防 anon 反复打 status (R8: 扫 100k 文件慢)
    'export':      {'max': 10,  'window': 60},     # 防已登录家长按错键 1 分钟 60 次 1MB JSON (R8)
    'grammar':     {'max': 120, 'window': 60},     # D6: 出题 — 命中缓存便宜,LLM 才花钱,120 够用
    'feedback':    {'max': 30,  'window': 60},     # D6: 跟读 — whisper+LLM 双重成本,压紧
    'global':      {'max': 600, 'window': 60},     # 兜底:任何端点都受这个限制
}
_API_LOCK = threading.Lock()  # 保护 _API_RATE (Phase 2 加锁)

# 清理阈值: dict 涨到这么大才值得扫一次,避免每个请求都遍历
_SWEEP_THRESHOLD = 512


def _sweep_stale_api_rate(now: float) -> int:
    """删掉整个已过期的 (ip, bucket) key,返回删了几条。

    为什么需要:`_api_rate_limit_ok` 只在某个 key 被再次访问时裁剪它自己的
    时间戳数组,从不过期删除整个 key。平板换 WiFi、DHCP 换 IP、设备上下线,
    都会留下永久条目 —— 长期跑 dict 单向增长,这是个慢性的内存泄漏。

    调用方负责持有 _API_LOCK,本函数自己不取锁(避免二次加锁死锁)。

    关键陷阱:各 bucket 的 window 差很多 (`import` 是 3600s,其余是 60s)。
    用全局最小 window 去淘汰,会把 `import` bucket 还没过期但暂时没访问的
    key 提前删掉 —— 结果是那个 IP 的上传限流被绕过。所以要按 bucket
    各自的 window 判断。
    """
    # 未达阈值不扫: 遍历全表的开销不能让它变成每个请求的固定成本
    if len(_API_RATE) < _SWEEP_THRESHOLD:
        return 0

    # 收集完再统一改 —— 遍历中增删 key 会 RuntimeError
    trims = {}       # key -> 剔除陈旧时间戳后的新数组
    stale_keys = []  # 窗口内已无请求,整个删掉
    for key, timestamps in _API_RATE.items():
        window = _API_LIMITS.get(key[1], _API_LIMITS['global'])['window']
        fresh = [t for t in timestamps if now - t < window]
        if not fresh:
            stale_keys.append(key)
        elif len(fresh) != len(timestamps):
            trims[key] = fresh

    for key, fresh in trims.items():
        _API_RATE[key] = fresh
    for key in stale_keys:
        del _API_RATE[key]

    return len(stale_keys)


def _api_rate_limit_ok(ip, bucket='global'):
    """返回 (ok, retry_after_sec). 超过限制时返回 (False, 至少 1 秒)"""
    with _API_LOCK:
        cfg = _API_LIMITS.get(bucket, _API_LIMITS['global'])
        now = time.time()
        key = (ip, bucket)
        arr = [t for t in _API_RATE.get(key, []) if now - t < cfg['window']]
        if len(arr) >= cfg['max']:
            retry = int(cfg['window'] - (now - arr[0]))
            return False, max(retry, 1)
        arr.append(now)
        _API_RATE[key] = arr
        _sweep_stale_api_rate(now)
        return True, 0


# === 鉴权 decorator ===
def require_parent_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('parent_auth'):
            return jsonify({"success": False, "error": "未授权"}), 401
        return f(*args, **kwargs)
    return wrapper