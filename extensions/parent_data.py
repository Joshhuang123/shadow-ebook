"""
Owns: parent PIN storage + verification, parent data CRUD (stats/vocab/settings),
anon child sync endpoint, parent session check, parent data export.
Does NOT own: login rate limit helpers / require_parent_auth (auth.py — imported).

Phase 3b: parent_data / parent_pin 改走 SQLite (data/shadow.db)。
R22 拆表: 原来全部学习数据塞在 parent_data 单行 JSON 里,阅读器每读一句、
每次查词都是 read-modify-write 整个 blob —— O(全量), 且 gunicorn 多 worker
下 last-write-wins 互相覆盖。现在:
  parent_section    stats / settings / vocabulary —— 整段小 JSON (深度合并语义)
  vocab_reviews     SRS 复习状态, 一词一行, 到期/统计/薄弱词走索引
  book_progress     阅读进度, 一书一行
  sentence_mastery  句子熟练度, 一句一行 (每书每句一条, 原整表重写的大头)
旧单行 blob 首启一次性迁入新表 (db._migrate_parent_split), 行保留作快照。

PIN 哈希格式: scrypt$salt_b64$hash_b64
  - 4 位 PIN 不加盐 = 10000 种可能, 离线秒破。加 scrypt + per-instance salt 缓这个
  - 旧格式 SHA-256 hex (无前缀) 仍能 verify, 首次成功登录时自动升级到 scrypt
"""
import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from flask import jsonify, request, session, Response

from extensions.auth import (
    require_parent_auth, _login_rate_limit_ok, _login_record_failure,
    _login_clear, _login_remaining, _api_rate_limit_ok,
)
from extensions.db import get_db, write_txn


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


# === R22 拆表: 存储层 ===
# 整段 JSON 的 section (深度合并语义, 数据量小, 不值得行化)
_SECTION_NAMES = ('stats', 'vocabulary', 'settings')


def _load_section(name: str, conn=None) -> dict:
    """读一个整段 JSON section (stats / settings / vocabulary)。坏数据当空段。"""
    conn = conn or get_db()
    row = conn.execute('SELECT data_json FROM parent_section WHERE name = ?', (name,)).fetchone()
    if not row:
        return {}
    try:
        data = json.loads(row['data_json'])
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f'parent_section[{name}] 解析失败, 返回空: {e}')
        return {}


def _save_section(name: str, data: dict, conn=None, now: int | None = None):
    conn = conn or get_db()
    now = now if now is not None else int(time.time() * 1000)
    conn.execute(
        'INSERT OR REPLACE INTO parent_section (name, data_json, updated_at) VALUES (?, ?, ?)',
        (name, json.dumps(data, ensure_ascii=False), now),
    )


def _review_row_to_dict(row) -> dict:
    """vocab_reviews 行 → API/旧 dict 形状 (六键, 与拆表前逐键一致)。"""
    return {
        'state': row['state'],
        'added_ts': row['added_ts'],
        'next_review_ts': row['next_review_ts'],
        'last_review_ts': row['last_review_ts'],
        'review_count': row['review_count'],
        'correct_count': row['correct_count'],
    }


def _load_parent_data() -> dict:
    """装配完整的 parent data 视图 (六键形状与拆表前完全一致)。

    只剩家长 dashboard / export 走这条路 —— 孩子端的热路径 (查词/翻页/复习)
    都改走下面的行级 helper, 不再为改一个字段读整个视图。
    """
    conn = get_db()
    vocab_reviews = {
        row['word']: _review_row_to_dict(row)
        for row in conn.execute('SELECT * FROM vocab_reviews')
    }
    book_progress = {
        row['book_id']: {
            'chapter_idx': row['chapter_idx'],
            'sentence_idx': row['sentence_idx'],
            'last_open_ts': row['last_open_ts'],
        }
        for row in conn.execute('SELECT * FROM book_progress')
    }
    sentence_mastery: dict = {}
    for row in conn.execute('SELECT * FROM sentence_mastery'):
        ch_map = sentence_mastery.setdefault(row['book_id'], {})
        sent_map = ch_map.setdefault(str(row['chapter_idx']), {})
        sent_map[str(row['sentence_idx'])] = {
            'mastery': row['mastery'],
            'attempts': row['attempts'],
            'last_attempt_ts': row['last_attempt_ts'],
        }
    return {
        "stats": _load_section('stats', conn),
        "vocabulary": _load_section('vocabulary', conn),
        "settings": _load_section('settings', conn),
        "vocabReviews": vocab_reviews,
        "bookProgress": book_progress,
        "sentenceMastery": sentence_mastery,
    }


def _save_parent_data(data: dict):
    """整份覆写 (旧语义保留): 给完整装配 dict 就全量替换, 缺哪个键就清空哪块。

    现在只剩 reset / 测试用; 业务热路径请走下面的行级 helper。
    """
    now = int(time.time() * 1000)
    with write_txn() as conn:
        for name in _SECTION_NAMES:
            section = data.get(name)
            if section is None:
                conn.execute('DELETE FROM parent_section WHERE name = ?', (name,))
            else:
                _save_section(name, section if isinstance(section, dict) else {}, conn, now)

        conn.execute('DELETE FROM vocab_reviews')
        for word, r in (data.get('vocabReviews') or {}).items():
            if not isinstance(r, dict):
                continue
            conn.execute(
                'INSERT OR REPLACE INTO vocab_reviews '
                '(word, state, added_ts, next_review_ts, last_review_ts, review_count, correct_count) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (str(word), str(r.get('state') or 'learning'),
                 int(r.get('added_ts') or now), int(r.get('next_review_ts') or 0),
                 int(r['last_review_ts']) if r.get('last_review_ts') is not None else None,
                 int(r.get('review_count') or 0), int(r.get('correct_count') or 0)),
            )

        conn.execute('DELETE FROM book_progress')
        for book_id, p in (data.get('bookProgress') or {}).items():
            if not isinstance(p, dict):
                continue
            conn.execute(
                'INSERT OR REPLACE INTO book_progress (book_id, chapter_idx, sentence_idx, last_open_ts) '
                'VALUES (?, ?, ?, ?)',
                (str(book_id), int(p.get('chapter_idx') or 0),
                 int(p.get('sentence_idx') or 0), int(p.get('last_open_ts') or now)),
            )

        conn.execute('DELETE FROM sentence_mastery')
        for book_id, chapters in (data.get('sentenceMastery') or {}).items():
            if not isinstance(chapters, dict):
                continue
            for ch, sents in chapters.items():
                if not isinstance(sents, dict):
                    continue
                for idx, m in sents.items():
                    if not isinstance(m, dict):
                        continue
                    try:
                        conn.execute(
                            'INSERT OR REPLACE INTO sentence_mastery '
                            '(book_id, chapter_idx, sentence_idx, mastery, attempts, last_attempt_ts) '
                            'VALUES (?, ?, ?, ?, ?, ?)',
                            (str(book_id), int(ch), int(idx),
                             str(m.get('mastery') or 'attempted'),
                             int(m.get('attempts') or 0), int(m.get('last_attempt_ts') or now)),
                        )
                    except (TypeError, ValueError):
                        continue
    _invalidate_weak_words_cache()


def load_child_profile() -> dict:
    """读出孩子档案 {name, age, lexile}。

    存在 settings section 的 child 键下。字段一律宽松处理:家长可能只填了蓝思没填年龄,
    可能填了 "8 岁" 这种带单位的手输,可能干脆什么都没填。
    解析失败一律退回 None,让阅读器用 DEFAULT_CHILD_LEXILE,
    绝不能因为档案写坏了就打不开书。
    """
    child = _load_section('settings').get('child')
    if not isinstance(child, dict):
        return {"name": "", "age": None, "lexile": None}

    def _as_int(v):
        # 允许 "600L" / "600 级" / " 600 " 这类手输
        m = re.search(r'-?\d+', str(v)) if v is not None else None
        return int(m.group(0)) if m else None

    return {
        "name": str(child.get('name') or '')[:40],
        "age": _as_int(child.get('age')),
        "lexile": _as_int(child.get('lexile')),
    }


def save_child_profile(profile: dict) -> dict:
    """写入孩子档案(家长页调用)。返回规范化后的档案。"""
    settings = _load_section('settings')
    settings['child'] = {
        'name': str(profile.get('name') or '')[:40],
        'age': profile.get('age'),
        'lexile': profile.get('lexile'),
    }
    _save_section('settings', settings)
    return load_child_profile()


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


# === R12: 行级写路径 (孩子端热路径, 单行 UPSERT, 不再整表重写) ===
def _record_vocab_lookup(word: str) -> dict:
    """孩子查词: 标 lookedWords, 同时进 SRS learning 桶。
    老词已存在 → 不重置状态 (避免复习间隔被无限重置)。
    返回该词当前 SRS 状态 {state, next_review_ts, review_count}。
    """
    word = word.strip().lower()
    if not word:
        return {}
    now = int(time.time() * 1000)
    with write_txn() as conn:
        conn.execute(
            'INSERT OR IGNORE INTO vocab_reviews '
            '(word, state, added_ts, next_review_ts, last_review_ts, review_count, correct_count) '
            "VALUES (?, 'learning', ?, ?, NULL, 0, 0)",
            (word, now, now + _srs_interval_ms('learning')),
        )
        # 旧行为兼容: lookup 同时把词标进 vocabulary.lookedWords
        # (前端 index.js 也会 shadowReport 上报一份, 这里保住不经前端的路径)
        vocab = _load_section('vocabulary', conn)
        vocab.setdefault('lookedWords', {})[word] = True
        _save_section('vocabulary', vocab, conn, now)
        row = conn.execute('SELECT * FROM vocab_reviews WHERE word = ?', (word,)).fetchone()
    _invalidate_weak_words_cache()
    return _review_row_to_dict(row)


def _record_vocab_review(word: str, correct: bool) -> dict | None:
    """孩子答对/答错一词, 推进 SRS 状态机。返回新状态, 词不存在返 None。"""
    word = word.strip().lower()
    now = int(time.time() * 1000)
    with write_txn() as conn:
        row = conn.execute('SELECT * FROM vocab_reviews WHERE word = ?', (word,)).fetchone()
        if row is None:
            return None
        new_state = _srs_next_state(row['state'], correct)
        updated = {
            'state': new_state,
            'added_ts': row['added_ts'],
            'next_review_ts': now + _srs_interval_ms(new_state),
            'last_review_ts': now,
            'review_count': row['review_count'] + 1,
            'correct_count': row['correct_count'] + (1 if correct else 0),
        }
        conn.execute(
            'UPDATE vocab_reviews SET state = ?, next_review_ts = ?, last_review_ts = ?, '
            'review_count = ?, correct_count = ? WHERE word = ?',
            (new_state, updated['next_review_ts'], now,
             updated['review_count'], updated['correct_count'], word),
        )
    _invalidate_weak_words_cache()
    return updated


def _get_due_reviews(limit: int = 20) -> list:
    """返回 next_review_ts <= now 的词列表, 按 next_review_ts 升序 (最久没过在前)。"""
    now = int(time.time() * 1000)
    rows = get_db().execute(
        'SELECT * FROM vocab_reviews WHERE next_review_ts <= ? '
        'ORDER BY next_review_ts ASC LIMIT ?',
        (now, limit),
    ).fetchall()
    return [(row['word'], _review_row_to_dict(row)) for row in rows]


def _vocab_state_counts() -> dict:
    """统计 4 桶词数 + 今日到期数 (GROUP BY, 不再扫全 dict)。"""
    conn = get_db()
    counts = {s: 0 for s in _SRS_STATES}
    for row in conn.execute('SELECT state, COUNT(*) AS c FROM vocab_reviews GROUP BY state'):
        if row['state'] in counts:
            counts[row['state']] = row['c']
    now = int(time.time() * 1000)
    due_now = conn.execute(
        'SELECT COUNT(*) AS c FROM vocab_reviews WHERE next_review_ts <= ?', (now,)
    ).fetchone()['c']
    total = conn.execute('SELECT COUNT(*) AS c FROM vocab_reviews').fetchone()['c']
    return {**counts, 'due_now': due_now, 'total': total}


# === R20: 薄弱词查询(供 feedback.py 喂回 LLM prompt) ===
def get_weak_words(limit: int = 10) -> list:
    """返回孩子历史薄弱词列表,按"错误率降序 + 复习次数降序"排。

    用途:feedback.py 拿到原句 + ASR 转写后,把孩子的薄弱词列表喂给 LLM,
    让反馈能针对性建议 ("你在 'th' 上一直有困难,这次原句里就有 'the',注意...")

    规则:
      - 排除已 mastered 的词(已掌握不算薄弱)
      - 排除 review_count=0 的词(没数据,没法算错误率)
      - 错误率 = 1 - correct_count / review_count
      - review_count 越大,排序越靠前(数据更可信,胜过只看过 1 次的"高错误率")

    D5: 30s TTL 缓存。feedback 每条录音都调,30s 够用户读完题 + 录音的窗口,
    又不会让薄弱词更新后延迟太久才生效。写操作(更新 vocabReviews)会主动
    invalidate,免得用户刚答对就还看到老数据。
    """
    cache_key = limit
    now = time.time()
    cached = _WEAK_WORDS_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _WEAK_WORDS_TTL_S:
        return cached[1]

    # 1 - correct*1.0/review == Python 里的 1 - correct/review, 逐位同源,
    # 排序结果与拆表前的实现一致
    rows = get_db().execute(
        "SELECT word FROM vocab_reviews "
        "WHERE state != 'mastered' AND review_count > 0 "
        "ORDER BY 1 - correct_count * 1.0 / review_count DESC, review_count DESC "
        "LIMIT ?",
        (limit,),
    ).fetchall()
    result = [row['word'] for row in rows]
    _WEAK_WORDS_CACHE[cache_key] = (now, result)
    return result


# === D5: weak_words 缓存 ===
_WEAK_WORDS_CACHE: dict = {}  # limit -> (timestamp, result)
_WEAK_WORDS_TTL_S = 30.0


def _invalidate_weak_words_cache():
    """写操作调,主动清缓存。让用户答对/答错后立刻看到更新。"""
    _WEAK_WORDS_CACHE.clear()


def _save_book_progress(book_id: str, chapter_idx: int, sentence_idx: int) -> dict:
    """保存孩子最近读到的位置。单行 UPSERT。返回新位置 dict。"""
    if not book_id:
        return {}
    now = int(time.time() * 1000)
    get_db().execute(
        'INSERT OR REPLACE INTO book_progress (book_id, chapter_idx, sentence_idx, last_open_ts) '
        'VALUES (?, ?, ?, ?)',
        (book_id, chapter_idx, sentence_idx, now),
    )
    return {'chapter_idx': chapter_idx, 'sentence_idx': sentence_idx, 'last_open_ts': now}


def _get_book_progress(book_id: str) -> dict | None:
    row = get_db().execute(
        'SELECT chapter_idx, sentence_idx, last_open_ts FROM book_progress WHERE book_id = ?',
        (book_id,),
    ).fetchone()
    if not row:
        return None
    return {'chapter_idx': row['chapter_idx'], 'sentence_idx': row['sentence_idx'],
            'last_open_ts': row['last_open_ts']}


def _get_all_book_progress() -> dict:
    return {
        row['book_id']: {
            'chapter_idx': row['chapter_idx'],
            'sentence_idx': row['sentence_idx'],
            'last_open_ts': row['last_open_ts'],
        }
        for row in get_db().execute('SELECT * FROM book_progress')
    }


def _record_sentence_mastery(book_id: str, chapter_idx: int, sentence_idx: int,
                              mastery: str, attempts: int = 1) -> dict | None:
    """记录某句子的 mastery (fluent / slow / attempted)。
    只升不降 (e.g. fluent 不会被 slow 覆盖), 避免录音抖动反复横跳。
    """
    if mastery not in ('fluent', 'slow', 'attempted'):
        return None
    now = int(time.time() * 1000)
    with write_txn() as conn:
        row = conn.execute(
            'SELECT mastery, attempts, last_attempt_ts FROM sentence_mastery '
            'WHERE book_id = ? AND chapter_idx = ? AND sentence_idx = ?',
            (book_id, chapter_idx, sentence_idx),
        ).fetchone()
        # 已 fluent 不再被覆盖 (除非新 attempts 远多于旧)
        if row and row['mastery'] == 'fluent' and mastery != 'fluent':
            return {'mastery': row['mastery'], 'attempts': row['attempts'],
                    'last_attempt_ts': row['last_attempt_ts']}
        new_attempts = (row['attempts'] if row else 0) + attempts
        conn.execute(
            'INSERT OR REPLACE INTO sentence_mastery '
            '(book_id, chapter_idx, sentence_idx, mastery, attempts, last_attempt_ts) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (book_id, chapter_idx, sentence_idx, mastery, new_attempts, now),
        )
    return {'mastery': mastery, 'attempts': new_attempts, 'last_attempt_ts': now}


def _get_sentence_mastery(book_id: str) -> dict:
    """返回 {chapter_idx: {sentence_idx: {mastery, attempts, last_attempt_ts}}}"""
    out: dict = {}
    for row in get_db().execute(
        'SELECT * FROM sentence_mastery WHERE book_id = ?', (book_id,)
    ):
        ch_map = out.setdefault(str(row['chapter_idx']), {})
        ch_map[str(row['sentence_idx'])] = {
            'mastery': row['mastery'],
            'attempts': row['attempts'],
            'last_attempt_ts': row['last_attempt_ts'],
        }
    return out


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
        now = int(time.time() * 1000)
        # 一个事务包住所有 section 的读改写: 两个 worker 同时上报也不会互相丢段
        with write_txn() as conn:
            for section in ('stats', 'vocabulary', 'settings'):
                if section in payload and isinstance(payload[section], dict):
                    current = _load_section(section, conn)
                    _deep_merge(current, payload[section])
                    _save_section(section, current, conn, now)
        return jsonify({"success": True})

    @app.route('/api/child/profile', methods=['POST'])
    @require_parent_auth
    def child_profile_save():
        """家长页保存孩子档案。读写都走独立接口,不动 /api/parent/data ——
        那个是孩子端免鉴权上报用的,拿它写档案等于把档案开放给任何人改。"""
        payload = request.json or {}
        if not isinstance(payload, dict):
            return jsonify({"success": False, "error": "请求格式不对"}), 400
        saved = save_child_profile(payload)
        return jsonify({"success": True, "child": saved})

    @app.route('/api/parent/reset', methods=['POST'])
    @require_parent_auth
    def parent_reset():
        with write_txn() as conn:
            conn.execute('DELETE FROM parent_section')
            conn.execute('DELETE FROM vocab_reviews')
            conn.execute('DELETE FROM book_progress')
            conn.execute('DELETE FROM sentence_mastery')
        _invalidate_weak_words_cache()
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
        try:
            limit = int(request.args.get('limit', 20))
        except (TypeError, ValueError):
            limit = 20
        limit = max(1, min(limit, 50))
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
        return jsonify({"success": True, "progress": _get_all_book_progress()})

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
