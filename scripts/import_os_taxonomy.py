#!/usr/bin/env python3
"""
导入 Marble Skill Taxonomy 的 English 子图,作为项目知识图谱的第二层。

  来源:https://github.com/withmarbleapp/os-taxonomy
  许可:数据库 ODbL 1.0(可商用,需署名,改库要保持开放)
        文本内容 CC BY-SA 4.0;curriculum-standards.json 各源各有许可
  规模:English 286 个 micro-topic / 内部依赖 534 条(347 hard + 187 soft)

为什么导入它:本项目自己手搓的 GRAMMAR_PREREQS 只有 24 个点(KET/PET),
覆盖的是「考试考什么」;这个图谱有 286 个点,覆盖的是「**按年龄该先会什么**」,
而且每条边都带 reason 和 hard/soft 强度。两层互补:
    grammar:*  —— 考试视角(KET/PET),本项目自有
    skill:*    —— 年龄/课标视角(Common Core / UK NC),外部导入

**它替代不了考试大纲**:小托福(TOEFL Junior)和剑桥通用五级的官方考纲是
ETS / 剑桥的版权材料,没有开放数据集。这里不猜、不抄,只把能核实的
开放数据引进来。

用法:
    python scripts/import_os_taxonomy.py            # 下载并导入
    python scripts/import_os_taxonomy.py --local    # 用已下载的本地文件
"""
import argparse
import json
import logging
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extensions.kg import upsert_edges, upsert_nodes  # noqa: E402


logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('import_os_taxonomy')


def log(msg):
    logger.info(msg)


BASE = 'https://raw.githubusercontent.com/withmarbleapp/os-taxonomy/main/data'
FILES = {
    'topics': f'{BASE}/topics.json',
    'dependencies': f'{BASE}/dependencies.json',
}
LOCAL = ROOT / 'data' / 'kg' / 'sources'

# 只导这三个域:语法是核心,拼读直接对应「跟读」,词汇是查词体验的一部分。
# Reading/Writing/Handwriting 属于读写训练,和本产品当前形态(阅读+跟读+查词)关系弱。
WANTED_DOMAINS = ('Grammar & Punctuation', 'Phonics & Word Reading', 'Vocabulary')

# 年龄 → 本项目的 level(1..5)。
# 项目的 KET=1 / PET=2 是考试等级,和这里的年龄档不是一回事,
# 所以 skill 节点单独一套 level,只用于「什么时候该教」。
AGE_BANDS = [
    ((0, 6), 1), ((7, 8), 2), ((9, 10), 3), ((11, 12), 4), ((13, 99), 5),
]

STRENGTH_WEIGHT = {'hard': 1.0, 'soft': 0.4}


def load(name, use_local):
    path = LOCAL / f'os_taxonomy_{name}.json'
    if use_local and path.exists():
        log(f'· 用本地文件 {path.name}')
        return json.loads(path.read_text(encoding='utf-8'))
    log(f'↓ 下载 {name}.json …')
    with urllib.request.urlopen(FILES[name], timeout=120) as r:
        data = json.loads(r.read().decode('utf-8'))
    LOCAL.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return data


def age_to_level(start, end):
    for (lo, hi), lvl in AGE_BANDS:
        if lo <= (start or lo) <= hi:
            return lvl
    return 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--local', action='store_true', help='不联网,用已下载文件')
    args = ap.parse_args()

    from extensions.db import get_db, init_db
    init_db()
    db = get_db()

    raw_topics = load('topics', args.local)
    raw_deps = load('dependencies', args.local)
    topics = raw_topics['topics'] if isinstance(raw_topics, dict) else raw_topics
    deps = raw_deps['dependencies'] if isinstance(raw_deps, dict) else raw_deps

    wanted = [t for t in topics
              if t.get('subject') == 'English'
              and t.get('domain') in WANTED_DOMAINS]
    ids = {t['id'] for t in wanted}
    log(f'· English 里 {len(ids)} 个主题落在 {WANTED_DOMAINS}')

    nodes = []
    for t in wanted:
        start, end = t.get('ageRangeStart'), t.get('ageRangeEnd')
        nodes.append((
            f"skill:{t['id']}", 'skill', t.get('name') or t['id'],
            age_to_level(start, end),
            {
                'domain': t.get('domain'),
                'type': t.get('type'),
                'age_start': start, 'age_end': end,
                'description': t.get('description') or '',
                'evidence': t.get('evidence') or [],
                'prompt': t.get('assessmentPrompt') or '',
                'standards': t.get('standards') or [],
                'source': 'os-taxonomy-v1',
            },
        ))

    edges = []
    for d in deps:
        if d.get('topicId') not in ids or d.get('prerequisiteId') not in ids:
            continue
        edges.append((
            f"skill:{d['topicId']}", 'requires', f"skill:{d['prerequisiteId']}",
            STRENGTH_WEIGHT.get(d.get('strength'), 0.6),
            d.get('reason') or '',
        ))

    hard = sum(1 for e in edges if e[3] >= 1.0)
    log(f'✓ 节点 {len(nodes)},边 {len(edges)}(硬 {hard} / 软 {len(edges) - hard})')

    upsert_nodes(nodes)
    upsert_edges(edges)

    # --- 落地校验:不能有悬空边 ---
    dangling = db.execute(
        '''SELECT COUNT(*) c FROM kg_edge
           WHERE src LIKE 'skill:%' AND src NOT IN (SELECT id FROM kg_node)'''
    ).fetchone()['c']
    if dangling:
        log(f'✗ 有 {dangling} 条悬空边,回滚')
        db.execute("DELETE FROM kg_edge WHERE src LIKE 'skill:%'")
        db.execute("DELETE FROM kg_node WHERE id LIKE 'skill:%'")
        return

    from extensions.kg import graph_stats
    log('')
    log('完成: %s' % json.dumps(graph_stats(), ensure_ascii=False))
    log('')
    log('署名要求(ODbL / CC BY-SA):')
    log('  Marble Skill Taxonomy (v1) · © Generative Spark, Inc. (Marble)')
    log('  https://withmarble.com · ODbL 1.0 (数据库) + CC BY-SA 4.0 (内容)')


if __name__ == '__main__':
    main()
