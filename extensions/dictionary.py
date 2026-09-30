"""
Owns: 查词 /api/dict/<word> —— 音标 + 中文释义,带 SQLite 缓存与多上游降级。
Does NOT own: 生词本 (parent_data.py)、朗读 (tts.py)、前端展示。

为什么要有这个模块(2026-09-30,用户报「点击查单词意思总是查询失败」):
    前端原来直接 fetch `https://api.dictionaryapi.dev/...` 拿英文释义,
    再 fetch mymemory 拿中文。这个 api. 子域在国内**根本连不上** ——
    实测 curl 12s 超时(000),而根域 dictionaryapi.dev 1.3s 就返回 403。
    是上游那台 Cloudflare 对这个子域的问题,不是我们的代码,也不是网络断了。
    于是「查词」在用户那边是 100% 失败,没有降级可言。

修法不是换个域名就算完,而是三件事:
    1. 查询挪到服务端 —— 前端不该依赖第三方是否可达(平板换网络就挂)。
    2. 主源换有道(实测 0.2s 可达,且中文释义+音标一次给全)。
    3. 缓存进 SQLite —— 同一个词反复查只打一次上游,断网也能用。
"""
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from flask import jsonify, request

from extensions.auth import _api_rate_limit_ok
from extensions.db import get_db

logger = logging.getLogger(__name__)

# 每个上游的超时。宁可换源也不要卡住:查词是点击反馈路径,超过 2s 就该有下一步。
UPSTREAM_TIMEOUT = 4.0
# 命中缓存的有效期。负缓存(上游说没这个词)短得多 —— 词表会变,
# 而且不存在的词多半是误点,短一点更容易自愈。
CACHE_TTL_OK = 30 * 86400
CACHE_TTL_MISS = 86400

_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36'

# 有道把词性写释义字符串开头 ("vt. 把…"),单独的 pos 字段常年是 null。
# 复合词性(n. & vt.)必须有真实分隔符 —— 早先这里写成 `\.\s*[a-z]{1,3}`,
# 结果 "aux. do not 的缩略形式" 里表示「不是」的 do 被当成词性吞掉,
# 整条释义因为「词性标记过长」被判无效,于是没有词性也没有释义。
_POS_RE = re.compile(r'^([a-z]{1,4}(?:\s*[&/]\s*[a-z]{1,3}\.?)?)\.?\s+')
_POS_CLEAN = re.compile(r'\.+$')


def normalize_word(raw: str) -> str:
    """把前端传来的原词规整成可查的形式。

    允许撇号和连字符('don't / well-known 是真词),其余非字母全丢。
    长度上限防住有人拿超长串去打上游。
    """
    if not raw:
        return ''
    w = raw.strip().lower()
    w = re.sub(r"[^a-z'\-]", '', w)
    w = re.sub(r"^[-']+|[-']+$", '', w)
    return w[:32]


def _get_json(url: str, timeout: float = UPSTREAM_TIMEOUT):
    """取 JSON。失败返回 None —— 上游各种怪状态码都不该冒到用户面前。"""
    req = urllib.request.Request(url, headers={
        'User-Agent': _UA,
        'Accept': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8', errors='replace'))
    except urllib.error.HTTPError as e:
        logger.info('查词上游 HTTP %s: %s', e.code, url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        logger.info('查词上游不可达 %s: %s', type(e).__name__, url)
    return None


def _clip(text: str, limit: int = 120) -> str:
    """有道有些词条是一整串 300 字的义项堆叠(run 就是),
    原样塞进弹窗会把整屏撑爆。截断在分号处,读起来仍是完整义项。"""
    text = (text or '').strip()
    if len(text) <= limit:
        return text
    cut = text.rfind('；', 0, limit)
    if cut < limit // 2:
        cut = limit
    return text[:cut].rstrip('，,、 ') + '…'


def _split_pos(text: str):
    """从有道的释义串里把词性切出来。

    "vt. 把(动物)赶上树" → ("vt.", "把(动物)赶上树")
    切不出来就返回 ("", 原文) —— 词性只是锦上添花,不能因此丢掉释义。
    """
    text = (text or '').strip()
    m = _POS_RE.match(text)
    if not m:
        return '', text
    pos = _POS_CLEAN.sub('', m.group(1))
    # 词性标记都很短且不含中文,过长的多半是误匹配(如 "Hello there" 的 Hello)
    if len(pos) > 6 or re.search(r'[a-z]', pos, re.I) is None:
        return '', text
    return pos + '.', text[m.end():].strip()


def _from_youdao(word: str):
    """有道 jsonapi。返回统一 payload 或 None(没这个词 / 不可达)。"""
    url = ('https://dict.youdao.com/jsonapi?q=' + urllib.parse.quote(word)
           + '&doctype=json&keyfrom=simple')
    data = _get_json(url)
    if not data:
        return None

    # simple 为 null 是有道「查无此词」的信号
    if not data.get('simple'):
        return {'word': word, 'phonetic': '', 'meanings': [], 'source': 'youdao'}

    entries = (data.get('ec') or {}).get('word') or []
    if not entries:
        return {'word': word, 'phonetic': '', 'meanings': [], 'source': 'youdao'}

    first = entries[0]
    phonetic = (first.get('ukphone') or first.get('usphone') or '').strip()

    meanings, seen = [], set()
    for group in first.get('trs') or []:
        for tr in group.get('tr') or []:
            for line in (tr.get('l') or {}).get('i') or []:
                pos, cn = _split_pos(line)
                if not cn:
                    continue
                key = (pos, cn)
                if key in seen:      # 有道同一个词条会重复给相同释义
                    continue
                seen.add(key)
                meanings.append({'part': pos, 'cn': _clip(cn)})
                if len(meanings) >= 6:
                    break
            if len(meanings) >= 6:
                break
        if len(meanings) >= 6:
            break

    return {'word': word, 'phonetic': phonetic, 'meanings': meanings, 'source': 'youdao'}


_POS_CN_TO_EN = {
    'n': 'noun', 'noun': 'noun',
    'v': 'verb', 'verb': 'verb', 'vt': 'verb', 'vi': 'verb',
    'adj': 'adjective', 'adjective': 'adjective',
    'adv': 'adverb', 'adverb': 'adverb',
    'prep': 'preposition', 'preposition': 'preposition',
    'conj': 'conjunction', 'conjunction': 'conjunction',
    'pron': 'pronoun', 'pronoun': 'pronoun',
    'int': 'interjection', 'interjection': 'interjection',
    'abbr': 'abbreviation', 'abbreviation': 'abbreviation',
}


def _from_datamuse(word: str):
    """datamuse 兜底:只给英文释义。

    价值比有道低一档(给孩子看中文才是关键),但总好过「查询失败」——
    有道整个挂掉时至少能给出 definition。
    """
    url = ('https://api.datamuse.com/words?sp=' + urllib.parse.quote(word)
           + '&md=d&max=1')
    data = _get_json(url)
    if not data:
        return None

    meanings = []
    for entry in data[:1]:
        tags = [t for t in (entry.get('tags') or []) if t in _POS_CN_TO_EN]
        part = _POS_CN_TO_EN[tags[0]] if tags else ''
        for d in (entry.get('defs') or [])[:4]:
            # datamuse 的 defs 形如 "verb: to give up"
            def_pos, _, rest = d.partition(':')
            if rest and def_pos.strip() in _POS_CN_TO_EN:
                part = _POS_CN_TO_EN[def_pos.strip()]
                d = rest.strip()
            meanings.append({'part': part, 'cn': d})

    # datamuse 不给音标,只能空着 —— 有道可用时它才是主源。
    return {'word': word, 'phonetic': '', 'meanings': meanings, 'source': 'datamuse'}


# 有道挂了就退到 datamuse。顺序即优先级。
PROVIDERS = (_from_youdao, _from_datamuse)


# === 缓存 ===

def _cache_get(word: str):
    conn = get_db()
    row = conn.execute(
        'SELECT payload, found, fetched_at FROM dict_cache WHERE word = ?', (word,)
    ).fetchone()
    if not row:
        return None
    ttl = CACHE_TTL_OK if row['found'] else CACHE_TTL_MISS
    if time.time() - row['fetched_at'] > ttl:
        return None
    return json.loads(row['payload'])


def _cache_put(word: str, payload: dict):
    found = 1 if payload.get('meanings') else 0
    conn = get_db()
    conn.execute(
        'INSERT OR REPLACE INTO dict_cache (word, payload, found, fetched_at) '
        'VALUES (?, ?, ?, ?)',
        (word, json.dumps(payload, ensure_ascii=False), found, int(time.time())),
    )


def lookup(word: str):
    """先查缓存,再按 PROVIDERS 顺序打上游。返回统一 payload。"""
    word = normalize_word(word)
    if not word:
        return None

    cached = _cache_get(word)
    if cached is not None:
        return cached

    last_err = None
    for provider in PROVIDERS:
        try:
            payload = provider(word)
        except Exception as e:      # 单个上游的怪数据不该让整条链断掉
            logger.warning('查词源 %s 异常: %s', provider.__name__, e)
            continue
        if payload is not None:
            _cache_put(word, payload)
            return payload
        last_err = provider.__name__

    logger.info('查词全部上游失败 word=%s 最后一个=%s', word, last_err)
    return None


def register_routes(app):
    @app.route('/api/dict/<path:word>')
    def dict_lookup(word):
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'dict')
        if not ok:
            return jsonify({'success': False, 'error': '查得太快啦,歇一下',
                            'retryable': True, 'retry_after': retry}), 429

        clean = normalize_word(word)
        if not clean:
            return jsonify({'success': False, 'error': '这不是一个单词'}), 400

        payload = lookup(clean)
        if payload is None:
            # 503 而不是 404:上游全挂是「稍后重试」,不是「这个词不存在」。
            # 前端据此显示不同的提示,别把网络问题说成「没查到」。
            return jsonify({'success': False, 'error': '词典连不上,检查一下网络',
                            'retryable': True}), 503
        return jsonify({'success': True, **payload})
