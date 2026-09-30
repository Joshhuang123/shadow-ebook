"""tests/test_dictionary.py — 查词不能依赖一个连不上的第三方。

背景(2026-09-30,用户报「点击查单词意思的功能现在总是查询失败」):
    前端原本直连 `https://api.dictionaryapi.dev/...` 拿英文释义,再直连
    mymemory 拿中文。实测那个 api. 子域**根本连不上**:

        curl -m 12 .../entries/en/tree  → 000 (12s 超时)
        curl -m 12 dictionaryapi.dev/... → 403 (1.3s 有响应)

    根域 1.3s 就回,子域 12s 挂 —— 是上游那台 Cloudflare 的问题,不是
    我们断网、也不是代码写错。所以在用户那边查词是 100% 失败,没降级可言。

修法(extensions/dictionary.py):查询挪到服务端,主源换有道(实测 0.2s
可达且一次给全音标+中文),datamuse 兜底,结果缓存进 SQLite。

本文件全部用录好的上游响应,不碰网络 —— 测试不该因为别人家 CDN 抖动而红。
"""
import json
import re
from pathlib import Path

import pytest

from extensions import db
from extensions import dictionary as dic

FIXTURES = Path(__file__).resolve().parent / 'fixtures'


def _fixture(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def app(tmp_db, clear_api_rate):
    from flask import Flask
    a = Flask(__name__)
    a.config['TESTING'] = True
    dic.register_routes(a)
    return a


@pytest.fixture
def client(app):
    return app.test_client()


# === 词的规整 ===

@pytest.mark.parametrize('raw,expected', [
    ('Tree', 'tree'),           # 大小写:页面上点的就是原文带大写的
    ('hello', 'hello'),
    ('  Hello  ', 'hello'),
    ("don't", "don't"),         # 撇号是词的一部分,不能吃掉
    ('well-known', 'well-known'),
    ('hello.', 'hello'),        # 句尾标点
    ('(tree)', 'tree'),
    ('a b', 'ab'),              # 空格直接拼掉
    ('123', ''),
    ('', ''),
    (None, ''),
])
def test_normalize_word(raw, expected):
    assert dic.normalize_word(raw) == expected


def test_normalize_word_caps_length():
    """超长串不能拿去打上游(也要防住有人拿它当放大器)。"""
    assert len(dic.normalize_word('a' * 500)) <= 32


# === 词性 / 义项的解析 ===

def test_split_pos_extracts_part_of_speech():
    assert dic._split_pos('vt. 把(动物)赶上树') == ('vt.', '把(动物)赶上树')
    assert dic._split_pos('n. 树（乔木）') == ('n.', '树（乔木）')
    assert dic._split_pos('aux. do not 的缩略形式') == ('aux.', 'do not 的缩略形式')


def test_split_pos_keeps_text_when_it_is_not_a_pos():
    """切不出词性时必须原样返回释义 —— 词性只是锦上添花。"""
    pos, cn = dic._split_pos('不要的;禁止')
    assert pos == '' and cn == '不要的;禁止'


def test_split_pos_does_not_eat_a_real_word():
    """'Hello there' 里的 Hello 不是词性,不能被吃掉当标签。"""
    pos, cn = dic._split_pos('Hello there, 打招呼')
    assert pos == '', f'把单词当词性了: {pos!r}'
    assert cn == 'Hello there, 打招呼'


def test_clip_truncates_run_on_definitions():
    """有道有些义项是 300 字堆叠,原样塞进弹窗会撑爆整屏。"""
    long_def = '跑，奔跑；' * 60
    out = dic._clip(long_def, limit=120)
    assert len(out) <= 121
    assert out.endswith('…')


def test_clip_leaves_short_text_alone():
    assert dic._clip('树（乔木）') == '树（乔木）'


# === 上游响应解析(用录好的真实响应)===

def test_parses_real_youdao_response(monkeypatch):
    monkeypatch.setattr(dic, '_get_json', lambda url, timeout=None: _fixture('youdao_tree.json'))
    p = dic._from_youdao('tree')
    assert p['phonetic'] == 'triː'
    assert p['source'] == 'youdao'
    assert [m['part'] for m in p['meanings']] == ['n.', 'vt.', 'vi.']
    assert '树' in p['meanings'][0]['cn']


def test_youdao_missing_word_is_a_clean_empty_hit(monkeypatch):
    """查无此词要有确定形状,不能和「上游挂了」混为一谈。"""
    monkeypatch.setattr(dic, '_get_json', lambda url, timeout=None: _fixture('youdao_zzzqqxxj.json'))
    p = dic._from_youdao('zzzqqxxj')
    assert p['meanings'] == []


def test_unreachable_upstream_returns_none(monkeypatch):
    """连不上就是 None —— 由 lookup 决定换源还是报错。"""
    monkeypatch.setattr(dic, '_get_json', lambda url, timeout=None: None)
    assert dic._from_youdao('tree') is None


def test_duplicate_meanings_are_collapsed(monkeypatch):
    """有道同一个词条会重复给相同释义,不去重弹窗里会连着出现两三遍。"""
    dup = {'simple': {'query': 'x'}, 'ec': {'word': [{
        'ukphone': 'x',
        'trs': [{'tr': [{'l': {'i': ['n. 树', 'n. 树']}}]},
                {'tr': [{'l': {'i': ['n. 树']}}]}],
    }]}}
    monkeypatch.setattr(dic, '_get_json', lambda url, timeout=None: dup)
    assert len(dic._from_youdao('x')['meanings']) == 1


# === 缓存:同一个词不该反复打上游 ===

def test_second_lookup_hits_cache(monkeypatch, tmp_db):
    calls = []

    def fake(url, timeout=None):
        calls.append(url)
        return _fixture('youdao_tree.json')

    monkeypatch.setattr(dic, '_get_json', fake)
    dic.lookup('tree')
    dic.lookup('tree')
    dic.lookup('TREE')            # 大小写不同也该命中同一个缓存条目
    assert len(calls) == 1, f'缓存没生效,打了 {len(calls)} 次上游'


def test_cache_survives_a_new_process(tmp_db):
    """缓存进 DB 而不是内存,换设备/重启后照样命中。"""
    dic._cache_put('tree', {'word': 'tree', 'phonetic': 'triː',
                            'meanings': [{'part': 'n.', 'cn': '树'}],
                            'source': 'youdao'})
    db.get_db().close()
    db._local.conn = None
    assert dic._cache_get('tree')['phonetic'] == 'triː'


def test_missing_word_is_cached_too(monkeypatch, tmp_db):
    """负缓存:不存在的词多半是误点,不该每次都去打上游。"""
    calls = []
    monkeypatch.setattr(dic, '_get_json',
                        lambda url, timeout=None: (calls.append(url), _fixture('youdao_zzzqqxxj.json'))[1])
    dic.lookup('zzzqqxxj')
    dic.lookup('zzzqqxxj')
    assert len(calls) == 1


def test_expired_cache_entry_is_refetched(monkeypatch, tmp_db):
    dic._cache_put('tree', {'word': 'tree', 'phonetic': 'triː', 'meanings': [], 'source': 'youdao'})
    db.get_db().execute('UPDATE dict_cache SET fetched_at = 0 WHERE word = ?', ('tree',))
    assert dic._cache_get('tree') is None, '过期条目仍被当成命中'


# === 降级链 ===

def test_falls_back_to_second_provider(monkeypatch, tmp_db):
    """有道整个挂掉时,datamuse 要能顶上,而不是直接报查询失败。"""

    def fake(url, timeout=None):
        if 'youdao' in url:
            return None
        return [{'word': 'tree', 'tags': ['noun'], 'defs': ['a tall plant']}]

    monkeypatch.setattr(dic, '_get_json', fake)
    p = dic.lookup('tree')
    assert p['source'] == 'datamuse'
    assert p['meanings'][0]['cn'] == 'a tall plant'
    assert p['meanings'][0]['part'] == 'noun'


def test_all_providers_down_returns_none(monkeypatch, tmp_db):
    monkeypatch.setattr(dic, '_get_json', lambda url, timeout=None: None)
    assert dic.lookup('tree') is None


def test_one_broken_provider_does_not_break_the_chain(monkeypatch, tmp_db):
    """某个源抛异常(怪 JSON、字段类型不对)时,链条要继续往下走。"""

    def boom(url, timeout=None):
        if 'youdao' in url:
            raise ValueError('上游今天心情不好')
        return [{'word': 'tree', 'tags': [], 'defs': ['a tall plant']}]

    monkeypatch.setattr(dic, '_get_json', boom)
    assert dic.lookup('tree')['source'] == 'datamuse'


# === HTTP 接口 ===

def test_route_returns_meanings(client, monkeypatch):
    monkeypatch.setattr(dic, '_get_json', lambda url, timeout=None: _fixture('youdao_abandon.json'))
    r = client.get('/api/dict/abandon')
    assert r.status_code == 200
    j = r.get_json()
    assert j['success'] is True
    assert j['phonetic'] == 'əˈbændən'
    assert j['meanings'][0]['cn']


@pytest.mark.parametrize('bad', ['123', '!!!', '---'])
def test_route_rejects_non_words(client, bad):
    """不是单词就别去打上游了。"""
    r = client.get(f'/api/dict/{bad}')
    assert r.status_code == 400
    assert r.get_json()['success'] is False


def test_route_says_503_when_upstreams_are_down(client, monkeypatch):
    """上游全挂是 503(稍后重试),不是「查无此词」—— 前端据此给不同提示。"""
    monkeypatch.setattr(dic, '_get_json', lambda url, timeout=None: None)
    r = client.get('/api/dict/tree')
    assert r.status_code == 503
    j = r.get_json()
    assert j['success'] is False
    assert j['retryable'] is True, '没标 retryable,前端会把它说成「没查到这个词」'


def test_route_known_word_upstream_down_is_still_503(client, monkeypatch):
    """有道有这个词、只是 datamuse 也挂 → 仍然算「查无此词」,但不是网络故障。"""
    monkeypatch.setattr(dic, '_get_json', lambda url, timeout=None: _fixture('youdao_zzzqqxxj.json'))
    r = client.get('/api/dict/zzzqqxxj')
    assert r.status_code == 200
    assert r.get_json()['meanings'] == []


# === 前端契约:别再直连那个连不上的域名 ===

def _web_src(name):
    return (Path(__file__).resolve().parent.parent / 'web' / name).read_text()


def _web_code(name):
    """源码去掉注释 —— 注释里当然可以提那个坏域名(就是要解释为什么换掉),
    真正不能出现的是会发出去的调用。"""
    src = _web_src(name)
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    # `//` 前面是 `:` 的当 URL 的一部分(https://),不当注释
    return re.sub(r'(?<!:)\/\/[^\n]*', '', src)


def test_word_lookup_no_longer_calls_the_dead_dictionary():
    """2026-09-30 的复发信号:查词路径上再出现 api.dictionaryapi.dev,
    查词就又会变成 100% 失败。

    只盯 lookupWord —— index.js 里 mymemory 还在,但那是**点句子看翻译**,
    不是查词(实测那个接口可达,没坏)。把两者混在一起断言会逼着人
    把好端点也一起砍掉。
    """
    idx = _web_code('js/index.js')
    body = idx[idx.index('async function lookupWord'):]
    body = body[:body.index('function closeWordModal')]
    assert 'api.dictionaryapi.dev' not in body, '查词又在直连那个连不上的词典'
    assert 'api.mymemory.translated.net' not in body, '查词又在直连第三方翻译'

    tutor = _web_code('js/tutor.js')
    t = tutor[tutor.index('async function lookupWord'):]
    t = t[:t.index('function showQuiz')]
    assert 'api.dictionaryapi.dev' not in t, '跟读页查词还在直连那个词典'


def test_frontend_reads_from_our_own_endpoint():
    for name in ('js/index.js', 'js/tutor.js'):
        assert '/api/dict/' in _web_code(name), f'{name} 没走服务端查词'


def test_tutor_lookup_escapes_upstream_text():
    """释义来自上游,插 innerHTML 前必须转义 —— 之前是没转义的。"""
    src = _web_src('js/tutor.js')
    body = src[src.index('async function lookupWord'):]
    body = body[:body.index('function showQuiz')]
    assert 'escapeHtml(m.cn)' in body, '释义没转义就插进 innerHTML 了'
    assert 'escapeHtml(j.phonetic)' in body


def test_csp_no_longer_needs_the_dictionary_host():
    """查词全在服务端,CSP 就不必再放行那个连不上的词典域名。

    mymemory 仍要留着 —— 点句子看翻译还在前端直连它。
    """
    app_py = (Path(__file__).resolve().parent.parent / 'app.py').read_text()
    csp = app_py[app_py.index('_CSP = '):app_py.index('def _add_security_headers')]
    assert 'dictionaryapi.dev' not in csp
    assert 'mymemory.translated.net' in csp, \
        '把翻译的 CSP 也砍了,「点句子看翻译」会在浏览器里被拦成失败'
