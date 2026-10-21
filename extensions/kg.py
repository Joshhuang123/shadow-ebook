"""
Owns: 知识图谱 —— 节点/边的写入与查询 + /api/kg/* 路由。

这个域回答一个问题:**孩子卡在哪一层?**

原设计里,语法点是一张平表(KET 11 个 + PET 12 个,平铺在 grammar.js 里),
孩子做错一道题,系统只知道「这个点错了」,不知道「是因为哪个前置没会」。
于是家长看到的是「英语不好」,孩子看到的是「我总是做错」,都没有可执行的下一步。

图谱做的事只有一件:把 24 个语法点按**前置依赖**排成有向无环图,
再把单词挂到它需要的语法点上、把音素挂到单词上。于是可以回答:

  - 这个词卡住,是因为哪个语法点没会?        (word → requires → grammar)
  - 音标里的这个音,这个年龄段该会了吗?        (word → contains → phoneme)
  - 按顺序练,下一个该练什么?                  (拓扑序 + mastery)

数据来源(都是可离线、可商用的开放许可,见 scripts/build_kg.py 顶部):
  ECDICT   MIT          英汉词典: 音标/词性/词频/考纲/词形变化
  CMUdict  BSD-4-Clause 发音词典: 单词 → ARPAbet 音素序列

设计取舍:
  - 节点/边只用两张通用表,字段差异塞 attrs JSON。窄表 + 一堆恒 NULL 的列
    比通用表更难查。
  - 前置关系手工维护在 GRAMMAR_PREREQS 里,不用算法猜。原因:算法能推出
    「被动语态比现在完成时难」,但推不出「被动语态必须先会现在完成时」。
    而这恰恰是家长要的那条边。
"""
import json
import logging
import sqlite3
import time

from flask import jsonify, request

from extensions.auth import _api_rate_limit_ok
from extensions.db import get_db


logger = logging.getLogger(__name__)


# 难度层:KET=1, PET=2。词/音素用 1..5 的细粒度难度。
LEVEL_KET = 1
LEVEL_PET = 2


# ============================================================================
# 语法前置图 (手工维护)
# ============================================================================
# title 抄自 web/js/grammar.js 的 GRAMMAR 定义。刻意不 import —— 那是前端
# 运行时对象,后端拿不到;两边靠 key 对齐,改了一边记得改另一边。
GRAMMAR_NODES = {
    # ---- KET (A2) ----
    'ket-pronouns':           ('代词系统',     LEVEL_KET),
    'ket-there-be':           ('There be 句型', LEVEL_KET),
    'ket-present-simple':     ('一般现在时',    LEVEL_KET),
    'ket-present-continuous': ('现在进行时',    LEVEL_KET),
    'ket-simple-past':        ('一般过去时',    LEVEL_KET),
    'ket-modals':             ('情态动词',      LEVEL_KET),
    'ket-imperative':         ('祈使句',        LEVEL_KET),
    'ket-prepositions':       ('介词用法',      LEVEL_KET),
    'ket-possessive':         ('名词所有格',    LEVEL_KET),
    'ket-comparatives':       ('形容词比较级',  LEVEL_KET),
    'ket-frequency':          ('频率表达',      LEVEL_KET),
    'ket-future-going-to':    ('be going to 表将来', LEVEL_KET),
    # ---- PET (B1) ----
    'pet-quantifiers':        ('数量词',        LEVEL_PET),
    'pet-conjunctions':       ('并列连词',      LEVEL_PET),
    'pet-gerund-infinitive':  ('动名词/不定式', LEVEL_PET),
    'pet-used-to':            ('used to',      LEVEL_PET),
    'pet-present-perfect':    ('现在完成时',    LEVEL_PET),
    'pet-past-perfect':       ('过去完成时',    LEVEL_PET),
    'pet-modals-perfect':     ('情态动词完成时', LEVEL_PET),
    'pet-passive':            ('被动语态',      LEVEL_PET),
    'pet-relatives':          ('定语从句',      LEVEL_PET),
    'pet-conditional':        ('条件句',        LEVEL_PET),
    'pet-adverb-clauses':     ('状语从句',      LEVEL_PET),
    'pet-reported-speech':    ('间接引语',      LEVEL_PET),
}

# A 的 requires 指向 B = 「学 A 之前必须先会 B」。
# 只连「真的缺了就没法做题」的边。难度相近但无依赖的不连 ——
# 图谱太密就退化成一张网,失去了「下一步该干什么」的意义。
GRAMMAR_PREREQS = {
    # --- KET 内部 ---
    'ket-there-be':           ['ket-pronouns'],
    'ket-present-simple':     ['ket-pronouns', 'ket-prepositions'],
    'ket-present-continuous': ['ket-present-simple', 'ket-there-be'],
    'ket-simple-past':        ['ket-present-simple'],
    'ket-frequency':          ['ket-present-simple'],
    'ket-comparatives':       ['ket-possessive'],
    'ket-future-going-to':    ['ket-present-simple', 'ket-modals'],
    'ket-possessive':         ['ket-pronouns'],

    # --- PET 全部建立在 KET 之上 ---
    'pet-present-perfect':    ['ket-simple-past', 'ket-present-simple'],
    'pet-past-perfect':       ['pet-present-perfect'],
    'pet-modals-perfect':     ['pet-present-perfect', 'ket-modals'],
    'pet-used-to':            ['ket-simple-past'],
    'pet-passive':            ['ket-present-simple', 'ket-simple-past',
                               'pet-present-perfect'],
    'pet-relatives':          ['ket-present-simple', 'ket-simple-past'],
    'pet-conditional':        ['ket-modals', 'ket-future-going-to'],
    'pet-adverb-clauses':     ['pet-conditional', 'ket-present-simple',
                               'ket-simple-past'],
    'pet-gerund-infinitive':  ['ket-modals', 'ket-present-continuous'],
    'pet-reported-speech':    ['ket-simple-past', 'ket-present-simple',
                               'ket-modals', 'pet-present-perfect'],
    'pet-quantifiers':        [],
    'pet-conjunctions':       [],
}

# ============================================================
# 考纲对照:小托福 / 剑桥通用五级 → 本项目的知识点
# ============================================================
# 为什么需要这一层
# ----------------
# 图谱里的 24 个点本来是「KET / PET 考什么」。但孩子实际在学的
# 可能是小托福(TOEFL Junior)、剑桥通用五级,或者某套教材的某个单元。
# 这几套的官方考纲都是**版权材料,没有开放的结构化数据集** ——
# 所以这里不做「从考纲生成知识点」,而是做**对照**:
# 把考纲的公开类目,映到本项目已经验证过的那 24 个点上。
#
# ⚠️ 这是本项目自己整理的对照,不是官方考纲原文。
# ETS / 剑桥的官方考纲是版权材料,不能拿我们的对照冒充它。
#
# 覆盖度(实测结论,见 docs/KG.md):
#   小托福 / 小雅思 覆盖的知识点几乎全在那 24 个 KET/PET 点里
#   (被动语态、定语/状语从句、非谓语动词、比较级),
#   真正缺的是**宾语从句** —— 而本项目没有单独拆这个点,
#   它被归在 pet-reported-speech(间接引语)里了。

# 语法页上有两类卡片:24 个「考点」(key 和图谱节点同名)、
# 9 个「教材讲解页」(present-progressive 这种 key)。
# 后者练起来也应该记到对应的知识点上,不然孩子的练习记录就丢了。
GRAMMAR_KEY_ALIASES = {
    'present-progressive': ['ket-present-continuous'],
    'simple-present':     ['ket-present-simple'],
    'simple-past':        ['ket-simple-past'],
    'frequency':          ['ket-frequency'],
    'be-going-to':        ['ket-future-going-to'],
    'want-to-do':         ['pet-gerund-infinitive'],
    'possessive-pronouns': ['ket-possessive', 'ket-pronouns'],
    'imperative':         ['ket-imperative'],
    # 三时态对比页:涉及三个时态,都记
    'tense-compare':      ['ket-present-simple', 'ket-present-continuous',
                           'ket-simple-past'],
}

# 掌握度衰减:多少天之后强度减半。
# 半年不练的「已掌握」就该退回「在学」—— 这是图谱「活」起来的关键:
# 它得反映孩子**现在**会什么,不是三个月前会什么。
MASTERY_HALF_LIFE_DAYS = 45.0

# 状态门槛(按正确率)
_MASTERY_MASTERED = 0.85
_MASTERY_FAMILIAR = 0.60


EXAM_SCOPES = {
    'toefl_junior': {
        'name': '小托福 TOEFL Junior',
        'note': 'ETS 官方考纲是版权材料,这里映射到本项目已验证的 24 个 KET/PET 点',
        'areas': [
            {
                'name': '阅读 Reading',
                'grammar': [
                    'ket-present-simple', 'ket-present-continuous',
                    'ket-simple-past', 'pet-present-perfect',
                    'ket-future-going-to', 'ket-comparatives',
                    'pet-passive', 'pet-relatives',
                    'pet-adverb-clauses', 'pet-gerund-infinitive',
                ],
            },
            {
                'name': '听力 Listening',
                'grammar': [
                    'ket-present-simple', 'ket-simple-past',
                    'ket-future-going-to', 'ket-frequency',
                    'ket-modals', 'pet-quantifiers', 'pet-conjunctions',
                ],
            },
            {
                'name': '口语 Speaking',
                'grammar': [
                    'ket-present-simple', 'ket-present-continuous',
                    'ket-simple-past', 'ket-future-going-to',
                    'ket-imperative', 'pet-gerund-infinitive',
                ],
            },
            {
                'name': '写作 Writing',
                'grammar': [
                    'ket-present-simple', 'ket-present-continuous',
                    'ket-simple-past', 'pet-present-perfect',
                    'ket-future-going-to', 'ket-modals', 'ket-imperative',
                    'pet-passive', 'pet-adverb-clauses', 'pet-gerund-infinitive',
                ],
            },
        ],
    },
    'cambridge_gkt': {
        'name': '剑桥通用五级 GKT',
        'note': '剑桥考纲是版权材料,这里映射到本项目已验证的 24 个 KET/PET 点',
        'areas': [
            {
                'name': '阅读 Reading',
                'grammar': [
                    'ket-present-simple', 'ket-present-continuous',
                    'ket-simple-past', 'pet-present-perfect',
                    'ket-future-going-to', 'ket-comparatives',
                    'pet-passive', 'pet-relatives', 'pet-adverb-clauses',
                    'pet-gerund-infinitive', 'pet-quantifiers',
                ],
            },
            {
                'name': '听力 Listening',
                'grammar': [
                    'ket-present-simple', 'ket-simple-past',
                    'pet-present-perfect', 'ket-future-going-to',
                    'ket-frequency', 'ket-modals', 'pet-quantifiers',
                    'pet-conjunctions',
                ],
            },
            {
                'name': '写作 Writing',
                'grammar': [
                    'ket-present-simple', 'ket-present-continuous',
                    'ket-simple-past', 'pet-present-perfect',
                    'ket-future-going-to', 'ket-modals', 'ket-imperative',
                    'pet-passive', 'pet-adverb-clauses', 'pet-gerund-infinitive',
                ],
            },
        ],
    },
}


def exam_scope(exam_id: str) -> dict:
    """考纲对照 + 每个考纲类目缺哪些前置。

    返回 {name, note, areas:[{name, grammar:[{key,label,level}],
    blocked:[{key,label}]}]}
    """
    scope = EXAM_SCOPES.get(exam_id)
    if not scope:
        return {}
    out = {'id': exam_id, 'name': scope['name'], 'note': scope['note'],
           'areas': []}
    for area in scope['areas']:
        keys = [k for k in area['grammar'] if k in GRAMMAR_NODES]
        # 这个类目里,哪些点的**前置**不在这个类目里 —— 那才是真正要补的
        blocked = []
        for k in keys:
            for pre in GRAMMAR_PREREQS.get(k, []):
                if pre not in keys and pre not in [b['key'] for b in blocked]:
                    blocked.append({'key': pre,
                                    'label': GRAMMAR_NODES[pre][0],
                                    'level': GRAMMAR_NODES[pre][1]})
        out['areas'].append({
            'name': area['name'],
            'grammar': [
                {'key': k, 'label': GRAMMAR_NODES[k][0],
                 'level': GRAMMAR_NODES[k][1]} for k in keys
            ],
            'blocked': blocked,
        })
    return out


def course_unit_graph(course_id: str = 'nc2a') -> list:
    """教材每个单元 → 它的知识点 + 缺哪些前置。

    单元的知识点来自 courses.py 的 COURSE_CONTENT(和内容放在一起,
    改教材时顺手改)。前置来自 GRAMMAR_PREREQS。
    """
    from extensions import courses
    if course_id != 'nc2a':
        return []
    out = []
    for i, unit in enumerate(courses.COURSE_CONTENT.get('units', [])):
        keys = [k for k in (unit.get('kg') or []) if k in GRAMMAR_NODES]
        blocked = []
        for k in keys:
            for pre in GRAMMAR_PREREQS.get(k, []):
                if pre not in keys and pre not in [b['key'] for b in blocked]:
                    blocked.append({'key': pre,
                                    'label': GRAMMAR_NODES[pre][0],
                                    'level': GRAMMAR_NODES[pre][1]})
        out.append({
            'index': i,
            'name': unit.get('name'),
            'grammar': [
                {'key': k, 'label': GRAMMAR_NODES[k][0],
                 'level': GRAMMAR_NODES[k][1]} for k in keys
            ],
            'blocked': blocked,
        })
    return out


# 为什么是这些边(留给以后的人,免得被当成随手写的):
#   现在完成时 ← 一般过去时:have done 的「done」就是过去式,不 Past 就没有 Done。
#   被动语态   ← 现在完成时:被动只有两个时态,难的那个是 have been + p.p.d,
#                       不会现在完成时就学不了最难的那个形态。
#   情态完成时 ← 现在完成时 + 情态动词:must have done 是两个已知块的拼装。
#   状语从句   ← 条件句:if/when 从句的语序规则和条件句是同一套。
#   间接引语   ← 现在完成时:转述里保留时态是 PET 必考,不会现在完成时就转不对。

# 单词 → 需要的语法点。key 是正则(小写)。
#
# 用法不是「句子里出现过就算」,而是**匹配片段要覆盖到这个词本身**
# (见 scripts/build_kg.py 的 _grammar_for_word)。所以这里的正则应当尽量
# 只框住真正承载该句型的那几个词,而不是框住整个句子。
# 故意不收的原则性介词 / 冠词 —— 它们出现的频率和句型无关,只会把图变噪。
WORD_GRAMMAR_RULES = [
    # 被动:必须有 be + 过去分词,光一个 by 不能算被动
    (r"\b(am|is|are|was|were|be|been|being)\s+(\w+ed|\w+n)\b", 'pet-passive'),
    # 现在完成时:have/has/had + 过去分词(整组框住,所以两个词都会拿到边)
    (r"\b(have|has|had)\s+(gone|been|done|seen|written|read|made|left|found|eaten|gone)\b",
     'pet-present-perfect'),
    (r"\b(have|has|had)\b.*\b(gone|been|done|seen|written|left|found|eaten)\b",
     'pet-present-perfect'),
    # 现在进行时:be + V-ing
    (r"\b(am|is|are|was|were|be|been)\s+(\w+ing)\b", 'ket-present-continuous'),
    # there be
    (r"\bthere\s+(is|are|was|were)\b", 'ket-there-be'),
    # 比较级
    (r"\b(than|more|less|bigger|smaller|better|worse|best|worst|tallest|biggest)\b",
     'ket-comparatives'),
    # 情态动词
    (r"\b(can|could|may|might|must|should|shall|would|ought)\b", 'ket-modals'),
    # be going to
    (r"\bgoing\s+to\b", 'ket-future-going-to'),
    # 频率副词(和它修饰的动词一起框住)
    (r"\b(never|always|usually|often|sometimes|rarely|ever|every\s+\w+)\s+\w+",
     'ket-frequency'),
    # 所有格:名词 + 's
    (r"([A-Za-z]{3,})'s\b", 'ket-possessive'),
    # 间接引语
    (r"\b(said|told|asked|replied)\b", 'pet-reported-speech'),
    # 定语从句:关系词 + 名词
    (r"\b(which|who|whose|whom)\s+[A-Za-z]+", 'pet-relatives'),
    # 条件句
    (r"\bif\b|\bwould\b|\bunless\b", 'pet-conditional'),
    # 状语从句
    (r"\b(although|though|because|while|whereas|so\s+that)\b", 'pet-adverb-clauses'),
    # 动名词/不定式
    (r"\b(enjoying|to\s+(go|eat|play|read|watch|study|see|make|take))\b",
     'pet-gerund-infinitive'),
    # 数量词
    (r"\b(a\s+lot\s+of|plenty\s+of|several|enough|many\s+of)\b", 'pet-quantifiers'),
    # 祈使句:靠句首的**动作动词**判定。刻意不写 `^[a-z]+` —— 那会匹配
    # 任意句子开头,把 there/then/the 全打成祈使句,纯噪声。
    (r"^\s*(please\s+)?(go|come|look|listen|open|close|take|put|stop|"
     r"read|write|run|walk|stand|sit|eat|drink|sleep|play|help|"
     r"turn|find|give|make|tell|remember|forget|watch|wait)\b", 'ket-imperative'),
    # used to
    (r"\bused\s+to\b", 'pet-used-to'),
]


# ============================================================================
# 写入
# ============================================================================
def _now() -> int:
    return int(time.time())


def upsert_nodes(rows):
    """rows: iterable of (id, kind, label, level, attrs_dict)。批量 UPSERT。"""
    db = get_db()
    now = _now()
    payload = [
        (nid, kind, label, level,
         json.dumps(attrs, ensure_ascii=False) if attrs else '{}', now)
        for nid, kind, label, level, attrs in rows
    ]
    db.executemany(
        '''INSERT INTO kg_node (id, kind, label, level, attrs, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             kind=excluded.kind, label=excluded.label, level=excluded.level,
             attrs=excluded.attrs, updated_at=excluded.updated_at''',
        payload,
    )


def upsert_edges(rows):
    """rows: iterable of (src, rel, dst, weight) 或 (src, rel, dst, weight, reason)。"""
    db = get_db()
    now = _now()
    payload = []
    for r in rows:
        if len(r) == 5:
            s, rel, d, w, reason = r
        else:
            s, rel, d, w = r
            reason = None
        payload.append((s, rel, d, w, reason, now))
    db.executemany(
        '''INSERT INTO kg_edge (src, rel, dst, weight, reason, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(src, rel, dst) DO UPDATE SET
             weight=excluded.weight, reason=excluded.reason,
             updated_at=excluded.updated_at''',
        payload,
    )


def seed_grammar_graph():
    """把 GRAMMAR_NODES / GRAMMAR_PREREQS 写进图谱。可重复执行(幂等)。"""
    nodes = [
        (f'grammar:{k}', 'grammar', title, level, {})
        for k, (title, level) in GRAMMAR_NODES.items()
    ]
    edges = [
        (f'grammar:{dst}', 'requires', f'grammar:{src}', 1.0)
        for dst, srcs in GRAMMAR_PREREQS.items()
        for src in srcs
    ]
    upsert_nodes(nodes)
    upsert_edges(edges)
    return len(nodes), len(edges)


# ============================================================================
# 查询
# ============================================================================
def _row_to_node(row):
    try:
        attrs = json.loads(row['attrs']) if row['attrs'] else {}
    except (TypeError, ValueError):
        attrs = {}
    return {
        'id': row['id'], 'kind': row['kind'], 'label': row['label'],
        'level': row['level'], 'attrs': attrs,
    }


def get_word(word: str):
    """单词节点 + 它的音素 + 它需要的语法点。查不到返回 None。"""
    db = get_db()
    w = word.strip().lower()
    row = db.execute('SELECT * FROM kg_node WHERE id=?', (f'word:{w}',)).fetchone()
    if not row:
        return None
    node = _row_to_node(row)

    phonemes = [r['dst'] for r in db.execute(
        "SELECT dst FROM kg_edge WHERE src=? AND rel='contains' ORDER BY rowid",
        (node['id'],))]
    grammar = [r['dst'] for r in db.execute(
        "SELECT dst FROM kg_edge WHERE src=? AND rel='requires' "
        "ORDER BY rowid", (node['id'],))]
    return {**node, 'phonemes': phonemes, 'grammar': grammar}


def graph_stats():
    db = get_db()
    out = {}
    for r in db.execute('SELECT kind, COUNT(*) c FROM kg_node GROUP BY kind'):
        out[r['kind']] = r['c']
    out['edges'] = db.execute('SELECT COUNT(*) c FROM kg_edge').fetchone()['c']
    return out


def skills_by_age(age=None, domain=None, limit=40):
    """按年龄取该阶段该会的技能点(来自 os-taxonomy 那层)。

    和 GRAMMAR 那层是**互补**不是替代:
      grammar:* 是考试视角(KET/PET),本项目自有
      skill:*   是年龄/课标视角(Common Core / UK NC),外部导入
    """
    db = get_db()
    sql = ['SELECT id, kind, label, level, attrs FROM kg_node', 'WHERE kind = ?']
    params: list = ['skill']

    if domain:
        sql.append("AND json_extract(attrs, '$.domain') = ?")
        params.append(domain)
    if age is not None:
        # age_range 是闭区间,age_start<=age<=age_end
        sql.append("AND json_extract(attrs, '$.age_start') <= ?")
        sql.append("AND json_extract(attrs, '$.age_end') >= ?")
        params += [age, age]

    sql.append('ORDER BY level, label LIMIT ?')
    params.append(limit)

    out = []
    for row in db.execute(' '.join(sql), params):
        node = _row_to_node(row)
        node['prereqs'] = [
            {'label': r['label'], 'reason': r['reason'], 'strength': r['weight']}
            for r in db.execute(
                '''SELECT n.label, e.reason, e.weight FROM kg_edge e
                   JOIN kg_node n ON n.id = e.dst
                   WHERE e.src = ? AND e.rel = 'requires' ''',
                (node['id'],))
        ]
        out.append(node)
    return out


def _decay(strength: float, updated_at_ms: int, now: float = None) -> float:
    """按时间衰减掌握强度(半衰期 MASTERY_HALF_LIFE_DAYS 天)。

    为什么要在**读的时候**算、而不是写的时候:
    孩子三个月前练对的题,不该今天还记着「已掌握」。
    写在读取时算,表里存的是原始成绩,衰减是「现在」的视角。
    """
    if strength <= 0:
        return 0.0
    now = now or time.time()
    age_days = max(0.0, (now - (updated_at_ms or 0) / 1000.0) / 86400.0)
    return strength * (0.5 ** (age_days / MASTERY_HALF_LIFE_DAYS))


def _state_for(strength: float) -> str:
    if strength >= _MASTERY_MASTERED:
        return 'mastered'
    if strength >= _MASTERY_FAMILIAR:
        return 'familiar'
    return 'learning'


def _mastery_map():
    """掌握度表 → {node_id: {state, strength}}。

    state 和 strength 都是**衰减后**的值 —— 所有消费方
    (learning_path / gaps / 家长页)看到的都是「现在会什么」。
    """
    db = get_db()
    now = time.time()
    out = {}
    for r in db.execute('SELECT * FROM kg_mastery'):
        strength = _decay(r['strength'], r['updated_at'], now)
        out[r['node_id']] = {
            'state': _state_for(strength),
            'strength': round(strength, 4),
            'raw_strength': r['strength'],
            'updated_at': r['updated_at'],
        }
    return out


def record_mastery(items) -> dict:
    """把语法练习成绩写进掌握度表。

    items: [{key, correct, total}]

    规则:
      · 一次练对不会「覆盖」之前练对的结果 —— 取**最好成绩**。
        孩子上次 100%、这次 40%,不该被判成「没掌握」。
        遗忘交给衰减处理(见 _decay),不靠「记最差的那次」。
      · 只有真正练过的点才写。练一次 0% 也算练过(state=learning),
        否则「未开始」和「练过但不会」分不开 —— 而这两件事给家长的
        建议是完全不同的。
    """
    db = get_db()
    now_ms = int(time.time() * 1000)
    written, skipped = [], []

    for item in (items or []):
        if not isinstance(item, dict):
            skipped.append(str(item)[:40])
            continue
        key = (item.get('key') or '').strip()
        try:
            correct = int(item.get('correct'))
            total = int(item.get('total'))
        except (TypeError, ValueError):
            skipped.append(key or '(无 key)')
            continue
        if total <= 0 or correct < 0 or correct > total:
            skipped.append(key or '(无 key)')
            continue

        targets = GRAMMAR_KEY_ALIASES.get(key, [key])
        targets = [t for t in targets if t in GRAMMAR_NODES]
        if not targets:
            skipped.append(key or '(无 key)')
            continue

        ratio = correct / total
        for t in targets:
            node_id = f'grammar:{t}'
            row = db.execute(
                'SELECT strength FROM kg_mastery WHERE node_id = ?', (node_id,)
            ).fetchone()
            best = max(float(row['strength']) if row else 0.0, ratio)
            db.execute(
                'INSERT OR REPLACE INTO kg_mastery (node_id, state, strength, updated_at) '
                'VALUES (?, ?, ?, ?)',
                (node_id, _state_for(best), best, now_ms),
            )
            written.append(t)

    db.commit()
    return {'written': written, 'skipped': skipped}


def mastery_summary() -> dict:
    """每个语法点的掌握状态(家长页和跟读页用)。"""
    mastery = _mastery_map()
    points = []
    for key, (title, level) in GRAMMAR_NODES.items():
        m = mastery.get(f'grammar:{key}')
        points.append({
            'key': key,
            'label': title,
            'level': level,
            'state': m['state'] if m else 'not-started',
            'strength': m['strength'] if m else 0.0,
        })
    counts = {'mastered': 0, 'familiar': 0, 'learning': 0, 'not-started': 0}
    for p in points:
        counts[p['state']] = counts.get(p['state'], 0) + 1
    return {
        'total': len(points),
        'counts': counts,
        'points': points,
    }


def learning_path(limit=6):
    """按拓扑序给出「下一个该学的语法点」。

    规则:一个点只有在**全部**前置都 mastered 时才算解锁,否则推荐它
    最弱的那个前置 —— 这正是家长那句话「卡住的不是难度,是顺序」。
    """
    db = get_db()
    mastery = _mastery_map()

    prereqs = {k: list(GRAMMAR_PREREQS.get(k, [])) for k in GRAMMAR_NODES}

    def is_mastered(key):
        m = mastery.get(f'grammar:{key}')
        return bool(m and m['state'] == 'mastered')

    pending = [k for k in GRAMMAR_NODES if not is_mastered(k)]

    # 未解锁的点里,找「前置缺口最浅」的那些 —— 越浅越该先做
    def depth(key, seen=None):
        seen = seen or set()
        if key in seen:
            return 0                      # 防环(种子数据不该有环,兜底)
        seen.add(key)
        ps = prereqs.get(key) or []
        return 0 if not ps else 1 + max(depth(p, seen) for p in ps)

    pending.sort(key=lambda k: (depth(k), GRAMMAR_NODES[k][1], k))

    out, seen_kinds = [], set()
    for key in pending:
        title, level = GRAMMAR_NODES[key]
        blockers = [p for p in prereqs[key] if not is_mastered(p)]
        out.append({
            'id': f'grammar:{key}',
            'label': title,
            'key': key,
            'level': level,
            'level_name': 'KET' if level == LEVEL_KET else 'PET',
            'ready': not blockers,
            'blockers': [{'label': GRAMMAR_NODES[b][0], 'key': b}
                          for b in blockers],
            'depth': depth(key),
        })
        if len(out) >= limit:
            break
    return out


def gaps():
    """前置缺口:每个未掌握的点,挡着它几个下游点。"""
    db = get_db()
    mastery = _mastery_map()

    def is_mastered(key):
        m = mastery.get(f'grammar:{key}')
        return bool(m and m['state'] == 'mastered')

    # 反向索引:每个点被谁依赖
    dependents = {k: [] for k in GRAMMAR_NODES}
    for dst, srcs in GRAMMAR_PREREQS.items():
        for src in srcs:
            dependents.setdefault(src, []).append(dst)

    rows = []
    for key in GRAMMAR_NODES:
        if is_mastered(key):
            continue
        title, level = GRAMMAR_NODES[key]
        blocked = [d for d in dependents.get(key, []) if not is_mastered(d)]
        if not blocked:
            continue          # 不挡着任何东西,不是缺口,只是还没学到
        rows.append({
            'id': f'grammar:{key}',
            'label': title,
            'level_name': 'KET' if level == LEVEL_KET else 'PET',
            'blocks': [{'label': GRAMMAR_NODES[b][0], 'key': b} for b in blocked],
            'block_count': len(blocked),
        })
    rows.sort(key=lambda r: -r['block_count'])
    return rows


# ============================================================================
# 路由
# ============================================================================
def register_routes(app):
    @app.route('/api/kg/stats')
    def kg_stats():
        return jsonify({'success': True, **graph_stats()})

    @app.route('/api/kg/word/<path:word>')
    def kg_word(word):
        node = get_word(word)
        if not node:
            return jsonify({'success': False, 'error': 'not found'}), 404
        return jsonify({'success': True, 'word': node})

    @app.route('/api/kg/path')
    def kg_path():
        return jsonify({'success': True,
                        'path': learning_path(
                            limit=request.args.get('limit', 6, type=int))})

    @app.route('/api/kg/gaps')
    def kg_gaps():
        return jsonify({'success': True, 'gaps': gaps()})

    @app.route('/api/kg/skills')
    def kg_skills():
        return jsonify({'success': True, 'skills': skills_by_age(
            age=request.args.get('age', type=int),
            domain=request.args.get('domain'),
            limit=request.args.get('limit', 40, type=int),
        )})

    @app.route('/api/kg/course')
    def kg_course():
        """教材单元 → 知识点 + 缺的前置。

        回答「孩子在第 3 单元卡住 → 是哪个前置没会」。
        """
        return jsonify({
            'success': True,
            'course': request.args.get('course', 'nc2a'),
            'units': course_unit_graph(request.args.get('course', 'nc2a')),
        })

    @app.route('/api/kg/exam/<exam_id>')
    def kg_exam(exam_id):
        """考纲对照(小托福 / 剑桥通用五级)。"""
        scope = exam_scope(exam_id)
        if not scope:
            return jsonify({'success': False, 'error': '没有这个考纲'}), 404
        return jsonify({'success': True, **scope})

    @app.route('/api/kg/exams')
    def kg_exams():
        """有哪些考纲对照可选。"""
        return jsonify({
            'success': True,
            'exams': [{'id': k, 'name': v['name'], 'note': v['note']}
                      for k, v in EXAM_SCOPES.items()],
        })

    @app.route('/api/kg/mastery', methods=['GET', 'POST'])
    def kg_mastery():
        """掌握度。

        GET  → 每个语法点现在的掌握状态(已掌握/在学/未开始)
        POST → 记一次练习结果:{items:[{key, correct, total}]}
               或单条 {key, correct, total}

        这是整张图谱**唯一的数据来源** —— 没有它,「下一个该练什么」
        只能按拓扑深度全量推荐,不是个性化诊断。
        """
        if request.method == 'GET':
            return jsonify({'success': True, **mastery_summary()})

        # 孩子端写的接口,但别让谁在局域网里刷它 —— 刷爆了掌握度
        # 就等于把「诊断」变成谎话。
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'kg')
        if not ok:
            return jsonify({'success': False,
                            'error': f'上报太频繁, {retry} 秒后再试'}), 429

        body = request.get_json(silent=True) or {}
        items = body.get('items')
        if items is None:
            items = [body] if body.get('key') else []
        if not isinstance(items, list):
            items = []
        if not items:
            return jsonify({'success': False, 'error': '没有练习结果'}), 400
        res = record_mastery(items)
        return jsonify({'success': True, **res, **mastery_summary()})

    @app.route('/api/kg/phonemes')
    def kg_phonemes():
        """音素层:跟读里哪些**音**还不稳。

        词级差异只说「这个词读错了」,但 18254 个词没法练。
        这里下沉到音素 —— 「/f/ 还不稳」才是能练的单位。
        """
        from extensions import phonemes as _ph
        try:
            return jsonify({'success': True, **_ph.summary()})
        except Exception as e:
            logger.warning('音素层读取失败: %s', e)
            return jsonify({'success': False, 'error': '音素层还没初始化',
                            'shaky': 0, 'counts': {}, 'list': []})

    @app.route('/api/kg/seed', methods=['POST'])
    def kg_seed():
        """家长页点一下就把语法前置图灌进去。幂等,重复调不会重复插。"""
        try:
            n, e = seed_grammar_graph()
            # 顺带把音素提示补齐(建图脚本早期只给元音写了提示)
            from extensions import phonemes as _ph
            hints = _ph.seed_phoneme_hints()
            return jsonify({'success': True, 'nodes': n, 'edges': e,
                            'phoneme_hints': hints})
        except sqlite3.Error as exc:
            logger.error('kg seed failed: %s', exc)
            return jsonify({'success': False, 'error': str(exc)}), 500
