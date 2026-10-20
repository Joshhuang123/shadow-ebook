"""音素层掌握度:跟读读不准,到底是不哪个**音**。

为什么要有这一层
----------------
跟读反馈给的是**词级**差异:「你把 castle 读成了 cassle」。
家长看到的是「这个词不会读」,孩子看到的是「我读错了一个词」——
但**词**是 18254 个的量级,「哪个音还不稳」才是能练的东西。
鱼和 chip 读错,问题多半出在 /ɪ/ 和 /tʃ/ 这一组音上,不是两个词。

所以这里把词级差异下沉到音素:CMUdict 的 ARPAbet 音素序列本来就在
知识图谱里(18 万条 `word → contains → phoneme` 边),直接拿来用。

怎么归因
--------
    期望词 castle(K AE S T AH L) vs 听到的 castle(同音素)
        → 音素完全一样 → 错在重音/语流,不是音素问题
    期望词 fish(F IH SH) vs 听到的 wish(W IH SH)
        → 差集 = {F} → 「/f/ 还不稳」← 精确
    期望词 castle vs 听到的 cassle(不是个词)
        → 没有对应音素 → 整词的音都算可疑(粗粒度)

粗粒度归因会连带冤枉这个词里本来没问题的音。所以两种归因要分开标,
界面上也要说清楚 —— 说不出是哪个音的时候,就说「这个词还不稳」。

掌握度怎么算
------------
音素用**指数移动平均**,不是「取最好成绩」:
  · 语法点会了就是会了,偶尔做错一套题不代表忘了;
  · 音素是「稳不稳」,读对一次也可能只是碰巧。
所以从 0.5(未知)起步,每次观察对半开:
  1 次读对 → 0.75(基本稳) → 2 次 → 0.875(稳了)
  1 次读错 → 0.25(不稳) → 再读对两次 → 0.66(基本稳)
和语法点一样,强度会随时间衰减(45 天半衰期)—— 半年不练的音
确实该再练练。
"""
import logging
import re
import time

logger = logging.getLogger(__name__)

# 观察权重:新观察占一半,旧值占一半
_ALPHA = 0.5
# 起始先验:完全未知
_PRIOR = 0.5
# 遗忘半衰期(天)—— 和语法点一致
HALF_LIFE_DAYS = 45.0

MASTERY_MASTERED = 0.85
MASTERY_FAMILIAR = 0.60

_WORD_RE = re.compile(r"[a-z']+")

SCHEMA = """
CREATE TABLE IF NOT EXISTS kg_phoneme_practice (
    phoneme_id  TEXT PRIMARY KEY,          -- 'phoneme:AH'
    strength    REAL NOT NULL DEFAULT 0.5, -- EMA,0.5 = 未知
    hits        INTEGER NOT NULL DEFAULT 0,
    misses      INTEGER NOT NULL DEFAULT 0,
    example     TEXT,                      -- 最近一次出问题的词
    updated_at  INTEGER NOT NULL
);
"""


def ensure_schema(db):
    db.executescript(SCHEMA)
    db.commit()


# === 音素查询 ===

def phonemes_for_word(word: str) -> list:
    """一个词的 ARPAbet 音素序列(大写,无重音标记)。

    走知识图谱的 `word → contains → phoneme` 边 —— 那是 CMUdict 建的,
    不重复造一份数据。
    """
    from extensions.db import get_db
    w = (word or '').strip().lower().strip("'")
    if not w:
        return []
    db = get_db()
    rows = db.execute(
        "SELECT dst FROM kg_edge WHERE src = ? AND rel = 'contains'", (f'word:{w}',)
    ).fetchall()
    return [r['dst'].split(':', 1)[1] for r in rows]


def phoneme_info(phoneme: str) -> dict:
    """音素的人话信息(提示语、是不是元音)。"""
    from extensions.db import get_db
    db = get_db()
    row = db.execute("SELECT label, level, attrs FROM kg_node WHERE id = ?",
                      (f'phoneme:{phoneme}',)).fetchone()
    if not row:
        return {'id': phoneme, 'label': phoneme, 'hint': '', 'vowel': False}
    import json
    try:
        attrs = json.loads(row['attrs'] or '{}')
    except Exception:
        attrs = {}
    return {
        'id': f'phoneme:{phoneme}',
        'label': row['label'],
        'level': row['level'],
        'hint': attrs.get('hint', ''),
        'vowel': bool(attrs.get('vowel')),
    }


# === 归因 ===

def blame_phonemes(expected: str, got: str) -> tuple:
    """词级差异 → 该负责的音素。

    返回 (音素列表, 是否精确)。
    精确 = 能确定是哪些音不同;不精确 = 整词都可疑。

    拿不到音素(词不在词库里)时返回空 —— 没有证据就不归因,
    宁可少说,不要说错。
    """
    exp = phonemes_for_word(expected)
    if not exp:
        return [], False
    if not got:
        # 漏读 → 整个词的音都算不稳
        return exp, False
    heard = phonemes_for_word(got)
    if not heard:
        # 听到的不是一个词(比如把 castle 读成 cassle)→ 粗粒度
        return exp, False
    diff = [p for p in exp if p not in heard]
    if diff:
        return diff, True
    # 音素完全一样(比如 two / too)→ 错在重音或语流,不是音素
    return exp, False


def word_alignment(sentence: str, transcript: str) -> list:
    """逐词对齐:原句每个词,孩子读得对不对。

    返回 [(expected, got_or_None, is_error), ...]
    """
    import difflib
    sent_words = [w for w in _WORD_RE.findall((sentence or '').lower())]
    trans_words = [w for w in _WORD_RE.findall((transcript or '').lower())]
    matcher = difflib.SequenceMatcher(None, sent_words, trans_words)
    out = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            for k in range(i1, i2):
                out.append((sent_words[k], trans_words[j1 + k - i1], False))
        elif tag == 'replace':
            for k in range(min(i2 - i1, j2 - j1)):
                out.append((sent_words[i1 + k], trans_words[j1 + k], True))
            # 一对多:多出来的原句词算漏读
            for k in range(min(i2 - i1, j2 - j1), i2 - i1):
                out.append((sent_words[i1 + k], None, True))
        elif tag == 'delete':
            for k in range(i1, i2):
                out.append((sent_words[k], None, True))
        # 'insert':孩子多读了词 —— 不归因到音素(可能是语流问题)
    return out


# === 记录 ===

def _decay(strength: float, updated_at_ms: int, now: float = None) -> float:
    if strength <= 0:
        return 0.0
    now = now or time.time()
    age_days = max(0.0, (now - (updated_at_ms or 0) / 1000.0) / 86400.0)
    return strength * (0.5 ** (age_days / HALF_LIFE_DAYS))


def _state_for(strength: float) -> str:
    if strength >= MASTERY_MASTERED:
        return 'mastered'
    if strength >= MASTERY_FAMILIAR:
        return 'familiar'
    return 'learning'


def record_alignment(alignment: list) -> dict:
    """把一次跟读的逐词结果写进音素掌握度。

    · 读对的词 → 它所有音素记一次 hit
    · 读错的词 → 被归因到的音素记一次 miss;归因不到就不记
    """
    from extensions.db import get_db
    db = get_db()
    ensure_schema(db)
    now_ms = int(time.time() * 1000)

    hits, misses, examples = {}, {}, {}

    for expected, got, is_error in (alignment or []):
        if not expected:
            continue
        if not is_error:
            for p in phonemes_for_word(expected):
                hits[p] = hits.get(p, 0) + 1
            continue
        blamed, precise = blame_phonemes(expected, got or '')
        for p in blamed:
            misses[p] = misses.get(p, 0) + 1
            if not examples.get(p):
                examples[p] = expected

    touched = set(hits) | set(misses)
    for p in touched:
        node_id = f'phoneme:{p}'
        row = db.execute(
            'SELECT strength, hits, misses, example FROM kg_phoneme_practice '
            'WHERE phoneme_id = ?', (node_id,)).fetchone()
        old_strength = float(row['strength']) if row else _PRIOR
        old_hits = int(row['hits']) if row else 0
        old_misses = int(row['misses']) if row else 0

        # 一个音素在一句话里可能出现多次,取平均观察值
        h = hits.get(p, 0)
        m = misses.get(p, 0)
        if h or m:
            obs = h / float(h + m)
        else:
            obs = old_strength
        strength = (1 - _ALPHA) * old_strength + _ALPHA * obs
        db.execute(
            'INSERT OR REPLACE INTO kg_phoneme_practice '
            '(phoneme_id, strength, hits, misses, example, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (node_id, strength, old_hits + h, old_misses + m,
             examples.get(p) or (row['example'] if row else None), now_ms),
        )
    db.commit()
    return {'phonemes': len(touched), 'hits': sum(hits.values()),
            'misses': sum(misses.values())}


def shaky_phonemes(limit: int = 8) -> list:
    """孩子读错过的音素(给家长页)。

    判据是「**读错过**」,不是「强度低」——
    早先按强度过滤,结果读错过的音被后面几次读对稀释掉,反而从列表里消失了。
    而那正是家长最该知道的那个音。
    从没读错过的音不列:一共 41 个,全列出来是噪声。

    排序:读错次数多的在前;次数一样时,当前强度低的在前。
    """
    from extensions.db import get_db
    db = get_db()
    ensure_schema(db)
    now = time.time()
    rows = db.execute('SELECT * FROM kg_phoneme_practice').fetchall()
    out = []
    for r in rows:
        if not r['misses']:
            continue                      # 从没读错过,没什么可说的
        strength = _decay(r['strength'], r['updated_at'], now)
        ph = r['phoneme_id'].split(':', 1)[1]
        info = phoneme_info(ph)
        out.append({
            'id': r['phoneme_id'],
            'label': info['label'],
            'hint': info['hint'],
            'vowel': info['vowel'],
            'strength': round(strength, 3),
            'state': _state_for(strength),
            'hits': r['hits'],
            'misses': r['misses'],
            'example': r['example'],
        })
    # 读错次数多的排前面;次数一样时更不稳的排前面
    out.sort(key=lambda x: (-x['misses'], x['strength']))
    return out[:limit]


def summary() -> dict:
    """音素层总览:多少个音还没稳。"""
    rows = shaky_phonemes(limit=999)
    counts = {'mastered': 0, 'familiar': 0, 'learning': 0}
    for r in rows:
        counts[r['state']] = counts.get(r['state'], 0) + 1
    return {
        'shaky': len(rows),
        'counts': counts,
        'list': rows,
    }


def all_phoneme_states() -> list:
    """所有练过的音的状态(给「练得怎么样」的完整视图)。"""
    from extensions.db import get_db
    db = get_db()
    ensure_schema(db)
    now = time.time()
    out = []
    for r in db.execute('SELECT * FROM kg_phoneme_practice').fetchall():
        strength = _decay(r['strength'], r['updated_at'], now)
        ph = r['phoneme_id'].split(':', 1)[1]
        info = phoneme_info(ph)
        out.append({
            'id': r['phoneme_id'], 'label': info['label'],
            'hint': info['hint'], 'vowel': info['vowel'],
            'strength': round(strength, 3), 'state': _state_for(strength),
            'hits': r['hits'], 'misses': r['misses'],
            'example': r['example'],
        })
    return out
