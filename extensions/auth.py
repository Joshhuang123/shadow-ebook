"""
Owns: parent PIN-protected route decorator, login rate limiting, generic API rate limiting.
Does NOT own: PIN storage / verification (parent_data.py).
"""
from functools import wraps
import time
from flask import jsonify, session


# === 登录限流: 防 LAN 上暴力破解 4 位 PIN ===
_LOGIN_WINDOW = {}  # ip -> [timestamp, ...]
MAX_ATTEMPTS = 5
WINDOW_SEC = 300    # 5 分钟窗口
LOCKOUT_SEC = 900   # 锁定 15 分钟


def _login_rate_limit_ok(ip):
    """返回 (ok, retry_after_sec). 锁定时返回 (False, 至少 1 秒)"""
    now = time.time()
    arr = _LOGIN_WINDOW.get(ip, [])
    arr = [t for t in arr if now - t < LOCKOUT_SEC]
    if len(arr) >= MAX_ATTEMPTS:
        retry = int(LOCKOUT_SEC - (now - arr[0]))
        return False, max(retry, 1)
    _LOGIN_WINDOW[ip] = arr
    return True, 0


def _login_record_failure(ip):
    arr = _LOGIN_WINDOW.setdefault(ip, [])
    arr.append(time.time())


def _login_clear(ip):
    _LOGIN_WINDOW.pop(ip, None)


# === 通用 API 限流: per-IP 滑动窗口 ===
_API_RATE = {}  # (ip, bucket) -> [timestamp, ...]
_API_LIMITS = {
    'tts':    {'max': 30,  'window': 60},   # 防 TTS 缓存爆
    'sync':   {'max': 60,  'window': 60},   # 防 anon 上报刷数据
    'global': {'max': 600, 'window': 60},   # 兜底:任何端点都受这个限制
}


def _api_rate_limit_ok(ip, bucket='global'):
    """返回 (ok, retry_after_sec). 超过限制时返回 (False, 至少 1 秒)"""
    cfg = _API_LIMITS.get(bucket, _API_LIMITS['global'])
    now = time.time()
    key = (ip, bucket)
    arr = [t for t in _API_RATE.get(key, []) if now - t < cfg['window']]
    if len(arr) >= cfg['max']:
        retry = int(cfg['window'] - (now - arr[0]))
        return False, max(retry, 1)
    arr.append(now)
    _API_RATE[key] = arr
    return True, 0


# === 鉴权 decorator ===
def require_parent_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('parent_auth'):
            return jsonify({"success": False, "error": "未授权"}), 401
        return f(*args, **kwargs)
    return wrapper


def register_routes(app):
    """auth 模块本身没有路由,只有装饰器和限流 helper。被其他模块 import 使用。"""
    pass