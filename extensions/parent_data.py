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
            data = json.loads(row['data_json'])
            # 补齐 R12 新增 section, 老数据没这些 key 也不报错
            data.setdefault('stats', {})
            data.setdefault('vocabulary', {})
            data.setdefault('settings', {})
            data.setdefault('vocabReviews', {})      # R12: SRS 状态机
            data.setdefault('bookProgress', {})      # R12: 阅读位置
            data.setdefault('sentenceMastery', {})   # R12: 句子熟练度
            return data
        except Exception as e:
            logger.warning(f'parent_data 解析失败, 返回空: {e}')
    return {
        "stats": {}, "vocabulary": {}, "settings": {},
        "vocabReviews": {}, "bookProgress": {}, "sentenceMastery": {},
    }


def _save_parent_data(data: dict):
    conn = get_db()
    now = int(time.time() * 1000)
    conn.execute(
        'INSERT OR REPLACE INTO parent_data (id, data_json, updated_at) VALUES (1, ?, ?)',
        (json.dumps(data, ensure_ascii=False), now)
    )


# === R12: 间隔重复 (SRS) 状态机 ===
# 4 桶: learning → practicing → familiar → mastered
# 第一次复习 (刚查的词) = 立即 (0d), 否则孩子查完就忘了
# 升级间隔: 0d / 2d / 5d / 14d
# 答错降一级, 立即重排到该级对应间隔
_SRS_INTERVALS_DAYS = {
    'learning':   0,   # 查完就复习
    'practicing': 2,
    'familiar':   5,
    'mastered':   14,
}
_SRS_STATES = ('learning', 'practicing', 'familiar', 'mastered')


def _srs_next_state(current: str, correct: bool) -> str:
    """返回答对/答错后的下一状态。

    答对: 升级一档 (mastered 保持)
    答错: 降一级 (learning 保持)
    """
    idx = _SRS_STATES.index(current) if current in _SRS_STATES else 0
    if correct:
        return _SRS_STATES[min(idx + 1, len(_SRS_STATES) - 1)]
    return _SRS_STATES[max(idx - 1, 0)]


def _srs_interval_ms(state: str) -> int:
    return _SRS_INTERVALS_DAYS.get(state, 1) * 86400 * 1000


# === R12: 句子熟练度判定 ===
# 不上 ASR (儿童口音不可靠), 用录音时长相对原句时长的比例:
#   < 0.5x  → 'attempted' (开口了但太短, 不算读了)
#   0.5-0.7 → 'slow' (读得慢但完整)
#   0.7-1.3 → 'fluent' (跟原句时长接近, 流畅)
#   > 1.3   → 'slow' (读得拖沓)
# 阈值是经验值, 不准没关系, 主要是给"读没读"一个信号
def calc_sentence_mastery(original_sec: float, recorded_sec: float) -> str:
    """录音时长 / 原句时长 → mastery 标签。返回 'fluent' / 'slow' / 'attempted'"""
    if original_sec <= 0 or recorded_sec <= 0:
        return 'attempted'
    ratio = recorded_sec / original_sec
    if ratio < 0.5:
        return 'attempted'
    if 0.7 <= ratio <= 1.3:
        return 'fluent'
    return 'slow'


# === R12: helper 调 _load / _save 时安全 merge 进已有数据 ===
def _record_vocab_lookup(word: str) -> dict:
    """孩子查词: 标 lookedWords, 同时进 SRS learning 桶。
    老词已存在 → 不重置状态 (避免复习间隔被无限重置)。
    返回该词当前 SRS 状态 {state, next_review_ts, review_count}。
    """
    word = word.strip().lower()
    if not word:
        return {}
    data = _load_parent_data()
    vocab = data.setdefault('vocabulary', {})
    vocab.setdefault('lookedWords', {})[word] = True

    reviews = data.setdefault('vocabReviews', {})
    now = int(time.time() * 1000)
    if word not in reviews:
        reviews[word] = {
            'state': 'learning',
            'added_ts': now,
            'next_review_ts': now + _srs_interval_ms('learning'),
            'last_review_ts': None,
            'review_count': 0,
            'correct_count': 0,
        }
    _save_parent_data(data)
    return reviews[word]


def _record_vocab_review(word: str, correct: bool) -> dict | None:
    """孩子答对/答错一词, 推进 SRS 状态机。返回新状态, 词不存在返 None。"""
    word = word.strip().lower()
    data = _load_parent_data()
    reviews = data.setdefault('vocabReviews', {})
    if word not in reviews:
        return None
    r = reviews[word]
    new_state = _srs_next_state(r['state'], correct)
    now = int(time.time() * 1000)
    r['state'] = new_state
    r['last_review_ts'] = now
    r['next_review_ts'] = now + _srs_interval_ms(new_state)
    r['review_count'] = r.get('review_count', 0) + 1
    if correct:
        r['correct_count'] = r.get('correct_count', 0) + 1
    _save_parent_data(data)
    return r


def _get_due_reviews(limit: int = 20) -> list:
    """返回 next_review_ts <= now 的词列表, 按 next_review_ts 升序 (最久没过在前)。"""
    data = _load_parent_data()
    reviews = data.get('vocabReviews', {})
    now = int(time.time() * 1000)
    due = [(w, r) for w, r in reviews.items() if r.get('next_review_ts', 0) <= now]
    due.sort(key=lambda x: x[1].get('next_review_ts', 0))
    return due[:limit]


def _vocab_state_counts() -> dict:
    """统计 4 桶词数 + 今日到期数。"""
    data = _load_parent_data()
    reviews = data.get('vocabReviews', {})
    counts = {s: 0 for s in _SRS_STATES}
    now = int(time.time() * 1000)
    due_now = 0
    for r in reviews.values():
        st = r.get('state', 'learning')
        if st in counts:
            counts[st] += 1
        if r.get('next_review_ts', 0) <= now:
            due_now += 1
    return {**counts, 'due_now': due_now, 'total': len(reviews)}


def _save_book_progress(book_id: str, chapter_idx: int, sentence_idx: int) -> dict:
    """保存孩子最近读到的位置。返回新位置 dict。"""
    if not book_id:
        return {}
    data = _load_parent_data()
    progress = data.setdefault('bookProgress', {})
    now = int(time.time() * 1000)
    progress[book_id] = {
        'chapter_idx': chapter_idx,
        'sentence_idx': sentence_idx,
        'last_open_ts': now,
    }
    _save_parent_data(data)
    return progress[book_id]


def _get_book_progress(book_id: str) -> dict | None:
    data = _load_parent_data()
    return data.get('bookProgress', {}).get(book_id)


def _record_sentence_mastery(book_id: str, chapter_idx: int, sentence_idx: int,
                              mastery: str, attempts: int = 1) -> dict | None:
    """记录某句子的 mastery (fluent / slow / attempted)。
    只升不降 (e.g. fluent 不会被 slow 覆盖), 避免录音抖动反复横跳。
    """
    if mastery not in ('fluent', 'slow', 'attempted'):
        return None
    data = _load_parent_data()
    sm = data.setdefault('sentenceMastery', {})
    book_sm = sm.setdefault(book_id, {})
    ch_sm = book_sm.setdefault(str(chapter_idx), {})
    key = str(sentence_idx)
    now = int(time.time() * 1000)
    existing = ch_sm.get(key)
    # 已 fluent 不再被覆盖 (除非新 attempts 远多于旧)
    if existing and existing.get('mastery') == 'fluent' and mastery != 'fluent':
        return existing
    ch_sm[key] = {
        'mastery': mastery,
        'attempts': (existing or {}).get('attempts', 0) + attempts,
        'last_attempt_ts': now,
    }
    _save_parent_data(data)
    return ch_sm[key]


def _get_sentence_mastery(book_id: str) -> dict:
    """返回 {chapter_idx: {sentence_idx: {mastery, attempts, last_attempt_ts}}}"""
    data = _load_parent_data()
    return data.get('sentenceMastery', {}).get(book_id, {})


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

    # === R12: 间隔重复 (SRS) 端点 ===
    @app.route('/api/vocab/lookup', methods=['POST'])
    def vocab_lookup():
        """anon: 孩子查词时调, 标 lookedWords + 进 SRS learning 桶。"""
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'sync')
        if not ok:
            return jsonify({"success": False, "error": f"上报过快, {retry} 秒后再试"}), 429
        word = (request.json or {}).get('word', '').strip().lower()
        if not word:
            return jsonify({"success": False, "error": "word 为空"})
        r = _record_vocab_lookup(word)
        return jsonify({"success": True, "review": r})

    @app.route('/api/vocab/review', methods=['POST'])
    def vocab_review():
        """anon: 孩子答对一词 (correct=true) 或答错 (correct=false)。"""
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'sync')
        if not ok:
            return jsonify({"success": False, "error": f"上报过快, {retry} 秒后再试"}), 429
        body = request.json or {}
        word = str(body.get('word', '')).strip().lower()
        correct = bool(body.get('correct'))
        if not word:
            return jsonify({"success": False, "error": "word 为空"})
        r = _record_vocab_review(word, correct)
        if r is None:
            return jsonify({"success": False, "error": "词不存在, 请先 lookup"}), 404
        return jsonify({"success": True, "review": r})

    @app.route('/api/vocab/review-queue', methods=['GET'])
    def vocab_review_queue():
        """anon: 返回今天该复习的词列表 (next_review_ts <= now), 按到期时间升序。"""
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'sync')
        if not ok:
            return jsonify({"success": False, "error": f"上报过快, {retry} 秒后再试"}), 429
        limit = min(int(request.args.get('limit', 20)), 50)
        due = _get_due_reviews(limit=limit)
        return jsonify({
            "success": True,
            "queue": [{"word": w, **r} for w, r in due],
        })

    @app.route('/api/vocab/stats', methods=['GET'])
    def vocab_stats():
        """anon: 4 桶词数 + 今日到期数。家长 dashboard 也用这个。"""
        return jsonify({"success": True, **_vocab_state_counts()})

    # === R12: 阅读位置 ===
    @app.route('/api/progress', methods=['POST'])
    def progress_save():
        """anon: 孩子读完一个句子, 存当前位置。
        body: {bookId, chapterIdx, sentenceIdx}"""
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'sync')
        if not ok:
            return jsonify({"success": False, "error": f"上报过快, {retry} 秒后再试"}), 429
        body = request.json or {}
        book_id = str(body.get('bookId', '')).strip()
        if not book_id:
            return jsonify({"success": False, "error": "bookId 为空"})
        try:
            chapter_idx = int(body.get('chapterIdx', 0))
            sentence_idx = int(body.get('sentenceIdx', 0))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "chapterIdx/sentenceIdx 必须为整数"})
        pos = _save_book_progress(book_id, chapter_idx, sentence_idx)
        return jsonify({"success": True, "progress": pos})

    @app.route('/api/progress/<book_id>', methods=['GET'])
    def progress_get(book_id):
        """anon: 读某本书的当前位置。无记录返 None。"""
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'sync')
        if not ok:
            return jsonify({"success": False, "error": f"上报过快, {retry} 秒后再试"}), 429
        return jsonify({"success": True, "progress": _get_book_progress(book_id)})

    @app.route('/api/progress', methods=['GET'])
    def progress_all():
        """anon: 所有书的进度 (家长 dashboard 用)。"""
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'sync')
        if not ok:
            return jsonify({"success": False, "error": f"上报过快, {retry} 秒后再试"}), 429
        data = _load_parent_data()
        return jsonify({"success": True, "progress": data.get('bookProgress', {})})

    # === R12: 句子熟练度 ===
    @app.route('/api/sentence/mastery', methods=['POST'])
    def sentence_mastery_save():
        """anon: 孩子读完一句录音后, 服务端/前端判 mastery 上来。
        body: {bookId, chapterIdx, sentenceIdx, mastery}"""
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'sync')
        if not ok:
            return jsonify({"success": False, "error": f"上报过快, {retry} 秒后再试"}), 429
        body = request.json or {}
        book_id = str(body.get('bookId', '')).strip()
        mastery = str(body.get('mastery', '')).strip()
        if not book_id or mastery not in ('fluent', 'slow', 'attempted'):
            return jsonify({"success": False, "error": "bookId 缺失或 mastery 不合法"})
        try:
            chapter_idx = int(body.get('chapterIdx', 0))
            sentence_idx = int(body.get('sentenceIdx', 0))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "chapterIdx/sentenceIdx 必须为整数"})
        r = _record_sentence_mastery(book_id, chapter_idx, sentence_idx, mastery)
        return jsonify({"success": True, "mastery": r})

    @app.route('/api/sentence/mastery/<book_id>', methods=['GET'])
    def sentence_mastery_get(book_id):
        """anon: 读某本书所有句子的 mastery。"""
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'sync')
        if not ok:
            return jsonify({"success": False, "error": f"上报过快, {retry} 秒后再试"}), 429
        return jsonify({"success": True, "mastery": _get_sentence_mastery(book_id)})
