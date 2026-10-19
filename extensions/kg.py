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


def _mastery_map():
    db = get_db()
    return {
        r['node_id']: {'state': r['state'], 'strength': r['strength']}
        for r in db.execute('SELECT * FROM kg_mastery')
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

    @app.route('/api/kg/seed', methods=['POST'])
    def kg_seed():
        """家长页点一下就把语法前置图灌进去。幂等,重复调不会重复插。"""
        try:
            n, e = seed_grammar_graph()
            return jsonify({'success': True, 'nodes': n, 'edges': e})
        except sqlite3.Error as exc:
            logger.error('kg seed failed: %s', exc)
            return jsonify({'success': False, 'error': str(exc)}), 500
