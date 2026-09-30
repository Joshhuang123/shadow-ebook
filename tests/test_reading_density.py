"""tests/test_reading_density.py — 每页句数该由「书 - 孩子」的差值决定。

背景(2026-09-30,用户提的「一直三句太死板,水平高的孩子就不用了」):
    每屏句数原来写死 3 句。但密度不该只看孩子水平 —— 同一本 500 蓝思的书,
    700 的孩子该看到一整页,400 的孩子该逐句啃。真正决定密度的是差值 gap:

        gap = bookLexile - childLexile
        gap 为负 → 书比孩子简单 → 少打断,多给内容(连续书页)
        gap 为正 → 书比孩子难   → 拆细、留白(大字聚焦)

本文件同时钉住 Python 与 JS 两份实现的一致性 —— 公式在两边各写了一份
(后端要能测、前端要能即时算),parity 测试防止它们悄悄漂移。
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from extensions import books as books_mod
from extensions.books import DEFAULT_CHILD_LEXILE, calc_reading_density

REPO = Path(__file__).resolve().parent.parent


# === 公式本身 ===

@pytest.mark.parametrize('book,child,expected', [
    # gap = book - child;档位是 gap <= upper,所以边界值归上一档
    (500, 700, 10),   # gap -200,书远简单于孩子
    (500, 750, 10),   # gap -250
    (500, 550, 7),    # gap  -50
    (500, 500, 5),    # gap    0 正好匹配
    (500, 400, 4),    # gap  100 略难
    (500, 350, 4),    # gap  150 —— 边界归 4 句档
    (500, 349, 3),    # gap  151 刚过界,掉到 3 句
    (500, 200, 3),    # gap  300 很难
    (880, 400, 3),    # gap  480 哈利波特配初级生
    (880, 900, 5),    # gap  -20 高段位读高段位,难度正好匹配
])
def test_density_by_gap(book, child, expected):
    assert calc_reading_density(book, child)['sentencesPerPage'] == expected


def test_boundaries_are_inclusive_at_upper_edge():
    """档位是 gap <= upper,边界值必须落在同一档。"""
    assert calc_reading_density(600, 800)['sentencesPerPage'] == 10   # gap -200
    assert calc_reading_density(700, 750)['sentencesPerPage'] == 7    # gap  -50
    assert calc_reading_density(650, 600)['sentencesPerPage'] == 5    # gap   50
    assert calc_reading_density(750, 600)['sentencesPerPage'] == 4    # gap  150
    # 刚过界就该掉一档
    assert calc_reading_density(600, 799)['sentencesPerPage'] == 7    # gap -199
    assert calc_reading_density(600, 801)['sentencesPerPage'] == 10   # gap -201
    assert calc_reading_density(751, 600)['sentencesPerPage'] == 3    # gap  151


def test_easier_book_gives_denser_page():
    """单调性:同一本书,孩子水平越高,每页句数不能变少。"""
    per = [calc_reading_density(500, c)['sentencesPerPage']
           for c in (300, 400, 500, 600, 700, 800, 900)]
    assert per == sorted(per), per


def test_mode_switches_to_book_page_when_easy():
    """gap 为负 → 连续书页;gap 转正 → 大字聚焦。切换点在 -50。"""
    assert calc_reading_density(500, 800)['mode'] == 'book'   # gap -300
    assert calc_reading_density(500, 700)['mode'] == 'book'   # gap -200
    assert calc_reading_density(500, 550)['mode'] == 'book'   # gap  -50 边界
    assert calc_reading_density(500, 549)['mode'] == 'focus'  # gap  -49
    assert calc_reading_density(500, 500)['mode'] == 'focus'  # gap    0


def test_missing_values_fall_back_not_crash():
    """缺档案 / 缺书难度都不能抛异常 —— 打不开一本书比密度算错严重得多。"""
    assert calc_reading_density(None, None)['sentencesPerPage'] > 0
    assert calc_reading_density('abc', 'xyz')['sentencesPerPage'] > 0
    assert calc_reading_density(500, None)['childLexile'] == DEFAULT_CHILD_LEXILE
    assert calc_reading_density(None, 600)['bookLexile'] == 500


def test_absurd_child_lexile_is_clamped():
    """填个 9999 不该让 gap 溢出成天文数字、进而顶到最大密度。"""
    r = calc_reading_density(1000, 9999)
    assert r['childLexile'] == 2000
    assert r['gap'] == -1000
    assert r['sentencesPerPage'] == 10


# === 与 JS 实现的一致性(parity)===

def _js_density_table():
    """从 web/js/index.js 里把 READING_DENSITY_STEPS 抠出来。"""
    src = (REPO / 'web/js/index.js').read_text()
    m = re.search(r'const READING_DENSITY_STEPS = \[(.*?)\];', src, re.S)
    assert m, 'index.js 里找不到 READING_DENSITY_STEPS'
    steps = []
    for row in re.findall(r'\[([^\]]+)\]', m.group(1)):
        parts = [p.strip() for p in row.split(',')]
        upper = None if parts[0] == 'null' else int(parts[0])
        steps.append((upper, int(parts[1]), parts[2].strip().strip("'")))
    return steps


def test_js_table_matches_python_table():
    """两份实现必须逐档一致,否则家长页预览和阅读器实际表现会对不上。"""
    assert _js_density_table() == [
        (s[0], s[1], s[2]) for s in books_mod.READING_DENSITY_STEPS
    ]


def test_js_default_child_lexile_matches_python():
    src = (REPO / 'web/js/index.js').read_text()
    assert f'const DEFAULT_CHILD_LEXILE = {DEFAULT_CHILD_LEXILE};' in src


def test_parent_preview_table_matches_python():
    """家长页那张预览表也复制了一份,同样要一致。"""
    src = (REPO / 'web/js/parent.js').read_text()
    m = re.search(r'const PROFILE_DENSITY_STEPS = \[(.*?)\];', src, re.S)
    assert m, 'parent.js 里找不到 PROFILE_DENSITY_STEPS'
    got = []
    for row in re.findall(r'\[([^\]]+)\]', m.group(1)):
        parts = [p.strip() for p in row.split(',')]
        got.append((None if parts[0] == 'null' else int(parts[0]), int(parts[1])))
    want = [(s[0], s[1]) for s in books_mod.READING_DENSITY_STEPS]
    assert got == want, f'家长页预览表和后端不一致:\n{got}\n{want}'
    assert f'const DEFAULT_CHILD_LEXILE = {DEFAULT_CHILD_LEXILE};' in src


# === 字号在两种形态下都必须可调 ===

def _reading_column_rule(selector):
    """从 ebook.css 里抠出某个选择器的 font-size 声明。"""
    css = (REPO / 'web/styles/pages/ebook.css').read_text()
    m = re.search(re.escape(selector) + r'\s*\{(.*?)\}', css, re.S)
    assert m, f'CSS 里找不到 {selector}'
    f = re.search(r'font-size:\s*([^;]+);', m.group(1))
    return f.group(1).strip() if f else ''


def test_focus_mode_respects_font_size_control():
    """聚焦模式的字号本来就跟着 --sentence-font-size 走(A- / A+ 能用)。"""
    assert '--sentence-font-size' in _reading_column_rule('.reading-column')


def test_book_mode_still_respects_font_size_control():
    """书页模式也必须跟着 --sentence-font-size 走。

    2026-09-30 的回归:加 mode-book 时把 font-size 写死成
    clamp(17px, 1.35vw, 21px),于是 A- / A+ 照常改了 CSS 变量,
    却没有一条规则读它 —— 按钮能点,字号纹丝不动。
    写死的 clamp 里不含 --sentence-font-size,就是复发信号。
    """
    rule = _reading_column_rule('.mode-book .reading-column')
    assert '--sentence-font-size' in rule, \
        f'mode-book 的字号又写死了, A-/A+ 会失效: {rule}'


def test_book_mode_font_size_varies_with_user_setting():
    """书页模式的字号必须真的随设定变化,不能只是「引用了变量」而已。"""
    css = (REPO / 'web/styles/pages/ebook.css').read_text()
    m = re.search(r'\.mode-book \.reading-column\s*\{(.*?)\}', css, re.S)
    decl = re.search(r'font-size:\s*([^;]+);', m.group(1)).group(1)
    # 必须是「按用户字号打折」的形式:含乘法且系数 < 1,
    # 这样默认 28px 出 20px,调到 40px 会真的变大。
    assert '*' in decl and '--sentence-font-size' in decl, decl
    coef = float(re.search(r'\*\s*([0-9.]+)', decl).group(1))
    assert 0 < coef < 1, f'系数 {coef} 没法让用户的选择真正生效: {decl}'


# === 端到端:档案接口 ===

@pytest.fixture
def app(tmp_db, clear_api_rate):
    from flask import Flask
    from extensions import parent_data as pd_mod
    a = Flask(__name__)
    a.config['TESTING'] = True
    a.config['SECRET_KEY'] = 'test-secret'
    books_mod.register_routes(a)
    pd_mod.register_routes(a)
    return a


@pytest.fixture
def client(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s['parent_auth'] = True
    return c


def test_profile_roundtrip(client):
    assert client.post('/api/child/profile',
                       json={'name': '小明', 'age': 8, 'lexile': 600}
                       ).get_json()['success'] is True
    c = client.get('/api/child/profile').get_json()['child']
    assert c == {'name': '小明', 'age': 8, 'lexile': 600}


def test_profile_readable_without_parent_auth(app, tmp_db):
    """阅读器是孩子端,拿不到 PIN,所以 profile 必须免鉴权可读。"""
    c = app.test_client()          # 没开 parent_auth 会话
    assert c.get('/api/child/profile').status_code == 200
    assert c.post('/api/child/profile',
                  json={'name': 'x', 'age': 1, 'lexile': 1}).status_code == 401


def test_profile_leaks_nothing_else(client):
    """免鉴权接口只能给算密度必需的字段,不能顺手把整张 parent_data 放开。"""
    r = client.get('/api/child/profile')
    assert set(r.get_json()['child']) == {'name', 'age', 'lexile'}
    assert 'vocabulary' not in r.get_json()
    assert 'stats' not in r.get_json()


@pytest.mark.parametrize('raw,expected', [
    ('600L', 600), (' 700 ', 700), ('800 级', 800), ('', None), (None, None), ('abc', None),
])
def test_lexile_parses_sloppy_parent_input(client, raw, expected):
    """家长手输 "600L" / "800 级" 很常见,不能因此把整份档案丢掉。"""
    # 家长页那个表单永远三个字段一起提交,所以 POST 是整份替换而不是深合并 ——
    # 「清空蓝思值」必须真的能清空,半合并会让它永远清不掉。
    client.post('/api/child/profile',
                json={'name': '小明', 'age': 8, 'lexile': raw})
    got = client.get('/api/child/profile').get_json()['child']
    assert got['lexile'] == expected
    assert got['name'] == '小明' and got['age'] == 8, '同一次提交里的字段不该互相丢'


def test_clearing_lexile_falls_back_to_default(client):
    """清空蓝思值后回到默认 600,而不是变成 0 把所有书都判成「极难」。"""
    client.post('/api/child/profile', json={'name': 'a', 'age': 8, 'lexile': 900})
    client.post('/api/child/profile', json={'name': 'a', 'age': 8, 'lexile': ''})
    got = client.get('/api/child/profile').get_json()['child']
    assert got['lexile'] is None
    assert calc_reading_density(500, got['lexile'])['childLexile'] == DEFAULT_CHILD_LEXILE


def test_broken_profile_does_not_break_reading(client):
    """档案写坏了,阅读器仍要能算出密度。"""
    client.post('/api/child/profile', json={'name': 'a', 'age': 8, 'lexile': '垃圾'})
    lex = client.get('/api/child/profile').get_json()['child']['lexile']
    assert lex is None
    d = calc_reading_density(500, lex)
    assert 3 <= d['sentencesPerPage'] <= 10


@pytest.mark.skipif(shutil.which('node') is None, reason='需要 node')
def test_js_compute_density_agrees_with_python():
    """真跑 JS 里的 computeDensity,逐档和 Python 对一遍。"""
    harness = REPO / 'tests' / 'density_parity_harness.js'
    proc = subprocess.run(['node', str(harness)], capture_output=True, text=True,
                          cwd=str(REPO), timeout=60)
    assert proc.returncode == 0, f'{proc.stdout}\n{proc.stderr}'
