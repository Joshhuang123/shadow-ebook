"""
Owns: parent PIN storage + verification, parent data CRUD (stats/vocab/settings),
anon child sync endpoint, parent session check, parent data export.
Does NOT own: login rate limit helpers / require_parent_auth (auth.py — imported).

Phase 3b: parent_data / parent_pin 改走 SQLite (data/shadow.db),
        原 data/parent/{data.json,pin.hash} 在首次启动时自动迁入,
        备份在 data/parent.migrated-<ts>/ 留 30 天。
"""
import hashlib
import json
import logging
import time
from flask import jsonify, request, session, Response

from extensions.auth import (
    require_parent_auth, _login_rate_limit_ok, _login_record_failure,
    _login_clear, _api_rate_limit_ok,
)
from extensions.db import get_db


logger = logging.getLogger(__name__)


def _hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode('utf-8')).hexdigest()


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
    return _hash_pin(str(pin)) == _load_pin_hash()


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


def register_routes(app):
    @app.route('/api/parent/check')
    def parent_check():
        return jsonify({"authenticated": bool(session.get('parent_auth'))})

    @app.route('/api/parent/login', methods=['POST'])
    def parent_login():
        ip = request.remote_addr or 'unknown'
        ok, retry = _login_rate_limit_ok(ip)
        if not ok:
            return jsonify({"success": False, "error": f"尝试次数过多, 请 {retry} 秒后再试"}), 429

        data = request.json or {}
        pin = str(data.get('pin', '')).strip()
        if not (pin.isdigit() and len(pin) == 4):
            _login_record_failure(ip)
            return jsonify({"success": False, "error": "PIN 必须是 4 位数字"}), 400
        if not _check_pin(pin):
            _login_record_failure(ip)
            return jsonify({"success": False, "error": "PIN 错误"}), 401
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
        _save_pin(_hash_pin(new))
        return jsonify({"success": True})

    @app.route('/api/parent/data', methods=['GET'])
    @require_parent_auth
    def parent_get_data():
        return jsonify({"success": True, "data": _load_parent_data()})

    @app.route('/api/parent/data', methods=['POST'])
    def parent_post_data():
        """孩子端 anon 上报 stats/vocab/settings, 不需要鉴权
        (合并写入, 不会覆盖整张表)"""
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'sync')
        if not ok:
            return jsonify({"success": False, "error": f"上报过快, {retry} 秒后再试"}), 429

        payload = request.json or {}
        current = _load_parent_data()
        for section in ('stats', 'vocabulary', 'settings'):
            if section in payload and isinstance(payload[section], dict):
                current.setdefault(section, {}).update(payload[section])
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
        payload = json.dumps(_load_parent_data(), ensure_ascii=False, indent=2)
        return Response(
            payload,
            mimetype='application/json',
            headers={'Content-Disposition': 'attachment; filename=shadow_learning_data.json'}
        )
