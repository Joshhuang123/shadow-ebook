"""tests/test_book_chapter_split.py — 整本书不能塌成 1 章。

背景(2026-09-30 修复的真实 bug):
    断章只靠「这个文件的纯文本短得像标题」。但 _clean_text 返回的是整个文件
    的全文 —— 几百词,永远不满足 _is_chapter_heading 的 ≤8 词 / ≤80 字符,
    于是 if 分支一次都不走,所有章节内容全堆进第 1 章。
    实测 magic tree house 29(真书,24 章)被压成 1 章 846 句。

    改成以 TOC 为主路径: 一条 TOC 条目 = 一章。

本测试的关键设计: 每个章节文件都写 **远超过标题长度** 的正文。
这样旧代码(靠"短得像标题"猜)必然全部落进第 1 章,新代码才切得开 ——
测试确实能抓住这个 bug,而不是在新代码上凑巧通过。
"""
import io
import json
import zipfile

import pytest

from extensions import books as books_mod
from extensions import db as db_mod


def _chapter_file(title: str, n_sentences: int = 30) -> str:
    """一个章节 XHTML,正文长到绝不可能被当成标题。"""
    body = ' '.join(f'Sentence {i} of {title} unfolds quietly.' for i in range(n_sentences))
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<h1>{title}</h1><p>{body}</p>
</body></html>"""


def _ncx(pairs) -> str:
    points = ''.join(
        f'<navPoint id="n{i}" playOrder="{i}"><navLabel><text>{label}</text></navLabel>'
        f'<content src="{href}"/></navPoint>'
        for i, (label, href) in enumerate(pairs, 1)
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
<head><meta name="dtb:uid" content="uid"/></head>
<docTitle><text>T</text></docTitle>
<navMap>{points}</navMap></ncx>"""


_TITLES = [
    ('Chapter One&#x2019;s Beginning', 'ch1.xhtml'),
    ('Chapter Two', 'ch2.xhtml'),
    ('Chapter Three', 'ch3.xhtml'),
    ('Chapter Four', 'ch4.xhtml'),
]


def _epub_epub2() -> bytes:
    """EPUB 2: NCX + spine,每个章节文件都长到不会被当成标题。"""
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Split Test Book</dc:title>
    <dc:creator>A. Author</dc:creator>
    <dc:identifier id="bid">urn:uuid:split-test</dc:identifier>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
    <item id="c3" href="ch3.xhtml" media-type="application/xhtml+xml"/>
    <item id="c4" href="ch4.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx"><itemref idref="c1"/><itemref idref="c2"/>
  <itemref idref="c3"/><itemref idref="c4"/></spine>
</package>"""

    container = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"
    media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('mimetype', 'application/epub+zip')
        z.writestr('META-INF/container.xml', container)
        z.writestr('OEBPS/content.opf', opf)
        z.writestr('OEBPS/toc.ncx', _ncx(_TITLES))
        for label, href in _TITLES:
            clean = label.replace('&#x2019;', "'")
            z.writestr(f'OEBPS/{href}', _chapter_file(clean))
    return buf.getvalue()


@pytest.fixture
def client(tmp_db, clear_api_rate):
    """app + 已鉴权会话 + 临时封面目录。"""
    cdir = tmp_db / 'covers'
    cdir.mkdir(exist_ok=True)
    original = books_mod.COVERS_DIR
    books_mod.COVERS_DIR = cdir
    try:
        from flask import Flask
        a = Flask(__name__)
        a.config['TESTING'] = True
        a.config['SECRET_KEY'] = 'test-secret'
        books_mod.register_routes(a)
        c = a.test_client()
        with c.session_transaction() as s:
            s['parent_auth'] = True
        yield c
    finally:
        books_mod.COVERS_DIR = original


def _import(client):
    return client.post(
        '/api/book/import',
        data={'epub': (io.BytesIO(_epub_epub2()), 'split.epub')},
        content_type='multipart/form-data',
    )


def _stored_chapters(client):
    """导入后从库里取回实际落盘的数据 —— 响应体只回计数,正文在 data_json 里。"""
    r = _import(client)
    assert r.status_code == 200, r.get_json()
    row = db_mod.get_db().execute(
        "SELECT data_json FROM books WHERE id='split_test_book'").fetchone()
    assert row is not None, '书没进库'
    return r.get_json(), json.loads(row[0])['chapters']


def test_toc_drives_chapter_split(client):
    """4 条 TOC → 4 章,不是 1 章。"""
    body, chapters = _stored_chapters(client)
    assert body['total_chapters'] == 4, f'期望 4 章,实际 {body["total_chapters"]}'

    names = [c['name'] for c in chapters]
    assert names == ['Chapter One’s Beginning', 'Chapter Two',
                     'Chapter Three', 'Chapter Four'], names


def test_each_chapter_holds_its_own_sentences(client):
    """各章句数应大致均等 —— 若内容全堆第 1 章,后面几章会是 0。"""
    _, chapters = _stored_chapters(client)
    counts = [len(c['sentences']) for c in chapters]
    assert len(counts) == 4
    # 每章都有内容,且没有一章吞掉全部
    assert all(n > 0 for n in counts), counts
    assert max(counts) < sum(counts), f'一章吞掉了全部内容: {counts}'


def test_toc_title_entities_are_unescaped(client):
    """NCX 里的 &#x2019; 必须解成真实字符,不能原样显示在目录上。"""
    _, chapters = _stored_chapters(client)
    assert chapters[0]['name'] == "Chapter One’s Beginning"
    assert '&#x' not in chapters[0]['name']
