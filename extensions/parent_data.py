"""
Owns: parent PIN storage + verification, parent data CRUD (stats/vocab/settings),
anon child sync endpoint, parent session check, parent data export.
Does NOT own: login rate limit helpers / require_parent_auth (auth.py — imported).

Phase 3b: parent_data / parent_pin 改走 SQLite (data/shadow.db),
        原 data/parent/{data.json,pin.hash} 在首次启动时自动迁入,
        备份在 data/parent.migrated-<ts>/ 留 30 天。

PIN 哈希格式: scrypt$salt_b64$hash_b64
  - 4 位 PIN 不加盐 = 10000 种可能, 离线秒破。加 scrypt + per-instance salt 缓这个
  - 旧格式 SHA-256 hex (无前缀) 仍能 verify, 首次成功登录时自动升级到 scrypt
"""
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from flask import jsonify, request, session, Response

from extensions.auth import (
    require_parent_auth, _login_rate_limit_ok, _login_record_failure,
    _login_clear, _login_remaining, _api_rate_limit_ok,
)
from extensions.db import get_db


logger = logging.getLogger(__name__)


# scrypt 参数: n=2^14 (16MB) 对 4 位 PIN 足够慢(单次 verify ~50ms), r=8, p=1
# 调到 n=2^15 需 ~200ms 一次, 当前规模没必要
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_SALT_BYTES = 16


def _hash_pin(pin: str) -> str:
    """生成新格式 PIN 哈希: scrypt$salt_b64$hash_b64"""
    salt = secrets.token_bytes(_SCRYPT_SALT_BYTES)
    h = hashlib.scrypt(
        pin.encode('utf-8'),
        salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN,
    )
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def _verify_pin(pin: str, stored: str) -> bool:
    """verify 一个 PIN 对一个 stored 字符串。返回 bool。

    支持两种格式:
      - 新: scrypt$salt_b64$hash_b64
      - 旧: SHA-256 hex (无前缀)
    """
    if stored.startswith('scrypt$'):
        try:
            _, salt_b64, hash_b64 = stored.split('$', 2)
            salt = base64.b64decode(salt_b64)
            expected = base64.b64decode(hash_b64)
            h = hashlib.scrypt(
                pin.encode('utf-8'),
                salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=len(expected),
            )
            return hmac.compare_digest(h, expected)
        except (ValueError, base64.binascii.Error):
            return False
    # 旧格式: 64 字符 hex = SHA-256
    if len(stored) == 64 and all(c in '0123456789abcdef' for c in stored):
        legacy = hashlib.sha256(pin.encode('utf-8')).hexdigest()
        return hmac.compare_digest(legacy, stored)
    return False


def _save_pin(pin_hash: str):
    """写 PIN 哈希到 SQLite (id=1 单行表)"""
    conn = get_db()
    now = int(time.time() * 1000)
    conn.execute(
        'INSERT OR REPLACE INTO parent_pin (id, pin_hash, updated_at) VALUES (1, ?, ?)',
        (pin_hash, now)
    )


def _load_pin_hash() -> str:
    """读取 PIN 哈希, 首次运行 (没迁过 pin.hash 也没改过 PIN) 写入默认 0000"""
    conn = get_db()
    row = conn.execute('SELECT pin_hash FROM parent_pin WHERE id = 1').fetchone()
    if row:
        return row['pin_hash']
    default = _hash_pin('0000')
    _save_pin(default)
    logger.warning('家长 PIN 首次初始化: 默认 0000, 请尽快修改')
    return default


def _check_pin(pin: str) -> bool:
    stored = _load_pin_hash()
    if _verify_pin(str(pin), stored):
        # 旧 SHA-256 格式首次 verify 成功 → 升级到 scrypt, 防止彩虹表
        if not stored.startswith('scrypt$'):
            _save_pin(_hash_pin(str(pin)))
            logger.info('PIN 已从 SHA-256 升级到 scrypt (一次性透明迁移)')
        return True
    return False


def _load_parent_data() -> dict:
    conn = get_db()
    row = conn.execute('SELECT data_json FROM parent_data WHERE id = 1').fetchone()
    if row:
        try:
            return json.loads(row['data_json'])
        except Exception as e:
            logger.warning(f'parent_data 解析失败, 返回空: {e}')
    return {"stats": {}, "vocabulary": {}, "settings": {}}


def _save_parent_data(data: dict):
    conn = get_db()
    now = int(time.time() * 1000)
    conn.execute(
        'INSERT OR REPLACE INTO parent_data (id, data_json, updated_at) VALUES (1, ?, ?)',
        (json.dumps(data, ensure_ascii=False), now)
    )


def _deep_merge(dst: dict, src: dict) -> dict:
    """递归合并 src 进 dst。规则:
      - 同 key 两边都是 dict → 递归
      - 否则 dst[key] = src[key] (覆盖)
    改 in-place, 返回 dst 便于链式。
    """
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def register_routes(app):
    @app.route('/api/parent/check')
    def parent_check():
        return jsonify({"authenticated": bool(session.get('parent_auth'))})

    @app.route('/api/parent/login', methods=['POST'])
    def parent_login():
        ip = request.remote_addr or 'unknown'
        ok, retry = _login_rate_limit_ok(ip)
        if not ok:
            return jsonify({
                "success": False,
                "error": f"尝试次数过多, 请 {retry} 秒后再试",
                "remaining": 0,
            }), 429

        data = request.json or {}
        pin = str(data.get('pin', '')).strip()
        if not (pin.isdigit() and len(pin) == 4):
            _login_record_failure(ip)
            return jsonify({
                "success": False,
                "error": "PIN 必须是 4 位数字",
                "remaining": _login_remaining(ip),
            }), 400
        if not _check_pin(pin):
            _login_record_failure(ip)
            return jsonify({
                "success": False,
                "error": "PIN 错误",
                "remaining": _login_remaining(ip),
            }), 401
        _login_clear(ip)
        session['parent_auth'] = True
        session.permanent = True
        return jsonify({"success": True})

    @app.route('/api/parent/logout', methods=['POST'])
    @require_parent_auth
    def parent_logout():
        session.pop('parent_auth', None)
        return jsonify({"success": True})

    @app.route('/api/parent/change-pin', methods=['POST'])
    @require_parent_auth
    def parent_change_pin():
        data = request.json or {}
        current = str(data.get('current', '')).strip()
        new = str(data.get('new', '')).strip()
        if not _check_pin(current):
            return jsonify({"success": False, "error": "当前 PIN 错误"}), 401
        if not (new.isdigit() and len(new) == 4):
            return jsonify({"success": False, "error": "新 PIN 必须是 4 位数字"}), 400
        if new == current:
            # 拒同值: 防止前端 bug 把当前 PIN 重复提交, 浪费一次"修改"操作
            # 也防止用 change-pin 误清 _LOGIN_WINDOW (虽然 _login_clear 在登录成功时已调, 这里也兜个底)
            return jsonify({"success": False, "error": "新 PIN 不能与当前 PIN 相同"}), 400
        _save_pin(_hash_pin(new))
        return jsonify({"success": True})

    @app.route('/api/parent/data', methods=['GET'])
    @require_parent_auth
    def parent_get_data():
        return jsonify({"success": True, "data": _load_parent_data()})

    @app.route('/api/parent/data', methods=['POST'])
    def parent_post_data():
        """孩子端 anon 上报 stats/vocab/settings, 不需要鉴权
        (深合并写入, 不会覆盖整张表 / 不会清掉嵌套 dict 已有的 key)"""
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'sync')
        if not ok:
            return jsonify({"success": False, "error": f"上报过快, {retry} 秒后再试"}), 429

        payload = request.json or {}
        current = _load_parent_data()
        for section in ('stats', 'vocabulary', 'settings'):
            if section in payload and isinstance(payload[section], dict):
                _deep_merge(current.setdefault(section, {}), payload[section])
        _save_parent_data(current)
        return jsonify({"success": True})

    @app.route('/api/parent/reset', methods=['POST'])
    @require_parent_auth
    def parent_reset():
        _save_parent_data({"stats": {}, "vocabulary": {}, "settings": {}})
        return jsonify({"success": True})

    @app.route('/api/parent/export')
    @require_parent_auth
    def parent_export():
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'export')
        if not ok:
            return jsonify({
                "success": False,
                "error": f"导出请求过快, {retry} 秒后再试",
                "retryable": True,
                "retry_after": retry,
            }), 429
        payload = json.dumps(_load_parent_data(), ensure_ascii=False, indent=2)
        return Response(
            payload,
            mimetype='application/json',
            headers={'Content-Disposition': 'attachment; filename=shadow_learning_data.json'}
        )
