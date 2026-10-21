#!/usr/bin/env python3
"""
构建英语学习知识图谱。

数据源(均可离线、可商用,已在 data/kg/sources/ 备好):
  ECDICT    https://github.com/skywind3000/ECDICT      MIT
            英汉词典。字段: word, phonetic, definition, translation, pos,
            collins, oxford, tag, bnc, frq, exchange, detail, audio
            tag 里带考纲(cet4/cet6/ielts/toefl/gre/zk/gk),
            frq 是 COCA 当代语料库词频排名(数字越小越常用)。

  CMUdict   https://github.com/cmusphinx/cmudict        BSD-4-Clause
            发音词典。word → ARPAbet 音素序列,带重音数字后缀(AE1 = 第一重音)。

只导入「孩子真的会用到」的词,不然 77 万条对 SQLite 是纯浪费:
  1. 已导入书籍里出现过的全部词(这是真实阅读轨迹)
  2. COCA 词频排名前 N 名(还没读到的,查词时能兜底)

用法:
    python scripts/build_kg.py --limit 30000          # 前 3 万高频词 + 书里出现的词
    python scripts/build_kg.py --limit 30000 --books-only
    python scripts/build_kg.py --download             # 先把原始数据拉下来
"""
import argparse
import csv
import json
import logging
import re
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extensions.kg import (  # noqa: E402
    GRAMMAR_PREREQS, WORD_GRAMMAR_RULES, seed_grammar_graph,
    upsert_edges, upsert_nodes,
)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('build_kg')


def log(msg):
    logger.info(msg)

SOURCES = ROOT / 'data' / 'kg' / 'sources'
ECDICT_CSV = SOURCES / 'ecdict.csv'
CMUDICT = SOURCES / 'cmudict.dict'

DOWNLOADS = {
    ECDICT_CSV: 'https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv',
    CMUDICT: 'https://raw.githubusercontent.com/cmusphinx/cmudict/master/cmudict.dict',
}

# 英语里几乎不出现在儿童读物里、也不值得查的高频虚词/缩写,
# 留着只会让「需要哪个语法点」的判断被噪声稀释。
STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'if', 'of', 'at', 'by', 'for',
    'with', 'about', 'into', 'to', 'from', 'in', 'out', 'on', 'off', 'up',
    'down', 'over', 'than', 'then', 'so', 'as', 'is', 'am', 'are', 'was',
    'were', 'be', 'been', 'being', 'do', 'does', 'did', 'have', 'has',
    'had', 'it', 'he', 'she', 'they', 'we', 'you', 'i', 'them', 'him',
    'her', 'us', 'my', 'your', 'his', 'its', 'our', 'their', 'this', 'that',
    'these', 'those', 'not', 'no', 'yes', 's', 't',
}

# 词形变化表 → 规范名。ECDICT 的 exchange 字段用 'p:d:perceived/p:...' 这种写法。
EXCHANGE_KINDS = {
    'p': 'past', 'd': 'past_participle', 'i': 'present_participle',
    '3': 'third_person', 'r': 'comparative', 't': 'superlative',
    's': 'plural', '0': 'lemma', '1': 'lemma_form',
}


def download():
    SOURCES.mkdir(parents=True, exist_ok=True)
    for path, url in DOWNLOADS.items():
        if path.exists():
            log(f'· 已存在,跳过 {path.name} ({path.stat().st_size//1024//1024}MB)')
            continue
        log(f'↓ 下载 {path.name} …')
        with urllib.request.urlopen(url, timeout=180) as r, open(path, 'wb') as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        log(f'✓ {path.name} {path.stat().st_size//1024//1024}MB')


def load_cmudict():
    """word -> [音素]。CMUdict 形如: 'read R EH1 D'"""
    out = {}
    if not CMUDICT.exists():
        log('! 没有 cmudict.dict,跳过音素层')
        return out
    with open(CMUDICT, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(';;;'):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            out[parts[0].lower()] = parts[1:]
    log(f'· cmudict: {len(out)} 词')
    return out


def words_in_books():
    """word -> [这个词出现过的句子]。

    只从**书里真实出现的句子**推语法,不用词典释义。
    早期版本拿 pos+definition 去匹配规则,结果 "castle"(象棋里的车,
    英文释义含 "chess can")被判成「需要情态动词」—— 图谱里挂错边比不挂
    更糟,因为整张图的价值就是「该练哪个」,挂错了会把孩子带偏。
    真实句子里的语法才是这个孩子真要面对的。
    """
    from extensions.db import get_db
    db = get_db()
    out = {}
    for r in db.execute("SELECT data_json FROM books"):
        try:
            book = json.loads(r['data_json'])
        except ValueError:
            continue
        # books.data_json 的形状: {'chapters': [{'name':..., 'sentences':[...]}]}
        for chap in book.get('chapters') or []:
            for s in chap.get('sentences') or []:
                text = s.get('text') if isinstance(s, dict) else s
                if not isinstance(text, str):
                    continue
                seen_here = set()
                for w in text.split():
                    w = w.strip("'\".,!?;:()").lower()
                    if not w.isalpha() or len(w) < 2:
                        continue
                    if w in seen_here:
                        continue
                    seen_here.add(w)
                    out.setdefault(w, []).append(text)
    log(f'· 书籍里出现的词: {len(out)}')
    return out


def difficulty_level(row):
    """把 ECDICT 的一行压成一个 1..5 的难度值,以及一句中文提示。"""
    collins = int(row['collins'] or 0)
    oxford = int(row['oxford'] or 0)
    tag = row['tag'] or ''
    # 考纲标签:越靠前越基础
    if 'zk' in tag or 'cet4' in tag:
        lvl = 1
    elif 'gk' in tag or 'cet6' in tag:
        lvl = 2
    elif 'ielts' in tag or 'toefl' in tag:
        lvl = 3
    elif 'gre' in tag:
        lvl = 4
    else:
        lvl = 5
    if collins == 5:
        lvl = min(lvl, 1)          # 柯林斯五星 = 母语者日常高频
    if oxford and lvl > 1:
        lvl -= 1                     # 牛津三千核心词往前提一档
    return max(1, min(5, lvl))


def parse_exchange(exchange):
    """'d:perceived/p:perceived/i:perceiving' -> {'past':'perceived', ...}"""
    out = {}
    if not exchange:
        return out
    for part in exchange.split('/'):
        if ':' not in part:
            continue
        code, _, val = part.partition(':')
        if code in EXCHANGE_KINDS and val:
            out[EXCHANGE_KINDS[code]] = val
    return out


def _words_with_spans(sentence):
    """[(word, start, end)] —— 单词在原句里的位置,用来判断匹配片段是否覆盖它。"""
    out = []
    for m in re.finditer(r"[A-Za-z']+", sentence):
        out.append((m.group(0).strip("'").lower(), m.start(), m.end()))
    return out


def _grammar_for_word(sentences, word):
    """这个词出现过的句子里,它**自己身上**带了哪些语法点。

    只认「匹配片段的字符范围覆盖了这个词」的句型。函数词本身不建节点,
    所以 by / 's 这类只沾到旁边实词的句型会自动落空。
    """
    found = set()
    for sent in sentences[:8]:
        spans = _words_with_spans(sent)
        # 这个词在句中的所有位置
        positions = [(s, e) for w, s, e in spans if w == word]
        if not positions:
            continue
        low = sent.lower()
        for pattern, gkey in WORD_GRAMMAR_RULES:
            for m in re.finditer(pattern, low):
                ms, me = m.span()
                # 匹配片段和词的区间有重叠 → 这个句型作用在这个词身上
                if any(ms < e and s < me for s, e in positions):
                    found.add(gkey)
                    break
        if len(found) >= 4:
            break
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=30000,
                    help='导入 COCA 词频前 N 名(加上书里出现的所有词)')
    ap.add_argument('--books-only', action='store_true',
                    help='只导书里出现过的词,不导高频表')
    ap.add_argument('--download', action='store_true',
                    help='先下载原始数据')
    args = ap.parse_args()

    if args.download:
        download()

    t0 = time.time()
    from extensions.db import get_db, init_db
    init_db()
    db = get_db()

    log('· 灌语法前置图 …')
    n, e = seed_grammar_graph()
    log(f'✓ 语法节点 {n} 个,前置边 {e} 条')

    cmudict = load_cmudict()
    book_ctx = words_in_books()

    if not ECDICT_CSV.exists():
        log('! 没有 ecdict.csv,只建了语法图。先跑 --download')
        return

    log(f'· 扫 ecdict.csv (取前 {args.limit} 词频) …')
    nodes, edges, phoneme_nodes = [], [], set()
    seen_words = set()
    count = 0
    matched = 0

    with open(ECDICT_CSV, encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            frq = int(row['frq'] or 0)
            # 书里出现的词不受词频门槛限制
            if not (0 < frq <= args.limit or row['word'].lower() in book_ctx):
                continue
            if frq == 0 and row['word'].lower() not in book_ctx:
                continue

            word = row['word'].strip().lower()
            if not word.isalpha() or len(word) < 2:
                continue
            if word in STOPWORDS or word in seen_words:
                continue
            seen_words.add(word)
            count += 1

            attrs = {
                'phonetic': row['phonetic'] or '',
                'cn': (row['translation'] or '').split('\n')[0],
                'pos': row['pos'] or '',
                'frq': frq,
                'bnc': int(row['bnc'] or 0),
                'collins': int(row['collins'] or 0),
                'oxford': int(row['oxford'] or 0),
                'tag': row['tag'] or '',
            }
            exchange = parse_exchange(row['exchange'])
            if exchange:
                attrs['forms'] = exchange
            nodes.append((f'word:{word}', 'word', row['word'], difficulty_level(row), attrs))

            # 词 → 音素
            if word in cmudict:
                phones = cmudict[word]
                for ph in phones:
                    base = re.sub(r'\d+$', '', ph)          # AE1 → AE
                    edges.append((f'word:{word}', 'contains', f'phoneme:{base}', 1.0))
                    phoneme_nodes.add(base)
                attrs['arpabet'] = phones

            # 词 → 需要的语法点。
            # 依据是**这个词所在的那个句子**用了什么句型,不是词典释义
            # (见 words_in_books 的注释)。而且只把**匹配片段里真的包含
            # 这个词**的句型挂上去 —— 否则 "by the castle" 里的 castle
            # 会被算成被动语态(by 的锅),"Tom's dog" 里的 dog 会被算成所有格
            # ('s 的锅)。挂错边比不挂更糟。
            if book_ctx.get(word):
                for gkey in _grammar_for_word(book_ctx[word], word):
                    edges.append((f'word:{word}', 'requires', f'grammar:{gkey}', 1.0))
                    matched += 1

            if count % 20000 == 0:
                log(f'   …已处理 {count} 词')

    log(f'✓ 词节点 {len(nodes)},边 {len(edges)},其中语法挂载 {matched}')
    log(f'· 音素 {len(phoneme_nodes)} 个')

    # ARPAbet 音素提示表:每个音怎么发,给跟读页和家长页用。
    # 提示语只有一份,在 extensions/phonemes.py 里(代码兜底 + 回填共用)。
    from extensions.phonemes import PHONEME_HINTS, VOWEL_HINTS
    for ph in sorted(phoneme_nodes):
        pnodes = ('phoneme', ph, 1, {
            'vowel': ph in VOWEL_HINTS,
            'hint': PHONEME_HINTS.get(ph, ''),
        })
        upsert_nodes([(f'phoneme:{ph}',) + pnodes])

    upsert_nodes(nodes)
    upsert_edges(edges)

    from extensions.kg import graph_stats
    log('')
    log('完成: %s' % json.dumps(graph_stats(), ensure_ascii=False))
    log('耗时 %.1fs' % (time.time() - t0))


if __name__ == '__main__':
    main()
