"""蓝思值在导入时算一次存进 data_json,列表/详情接口直接读。

之前 /api/books 每次缓存失效、/api/book/<id> 每次打开书,都要对每本书
做一次 calc_lexile —— 扫全书句子 + 正则过滤,哈利波特一本 6.7MB。
改成导入时算好存 `lexile` 字段,读取路径走 _book_lexile:
  - 有合法存储值 → 直接用 (零扫描)
  - 老书没有该字段 / 值不合法 → 退回现场计算,行为不变
"""
import io
import json
import zipfile

import pytest

from extensions import books as books_mod
from extensions.db import get_db


def test_book_lexile_prefers_stored_value(monkeypatch):
    """存了合法 lexile 就不许再全量扫描 —— 把 calc_lexile 换成炸弹来钉死。"""
    def boom(data):
        raise AssertionError('已有存储值还去重算 lexile')

    monkeypatch.setattr(books_mod, 'calc_lexile', boom)
    assert books_mod._book_lexile({'lexile': 880}) == 880


def test_book_lexile_rejects_bad_stored_values():
    """bool 是 int 的子类、字符串、越界值都不能直接采信,必须退回计算。"""
    fallback_data = {'lexile': '垃圾', 'chapters': []}
    assert books_mod._book_lexile({'lexile': True, 'chapters': []}) == 500
    assert books_mod._book_lexile({'lexile': '880', 'chapters': []}) == 500
    assert books_mod._book_lexile({'lexile': 0, 'chapters': []}) == 500
    assert books_mod._book_lexile({'lexile': 99999, 'chapters': []}) == 500
    assert books_mod._book_lexile({}) == 500          # 老书无字段
    assert books_mod._book_lexile(fallback_data) == \
        books_mod.calc_lexile(fallback_data)


# === 导入路径集成: 导入一次,lexile 落进 data_json ===

@pytest.fixture
def client(tmp_db, clear_api_rate):
    from flask import Flask
    a = Flask(__name__)
    a.config['TESTING'] = True
    a.config['SECRET_KEY'] = 'test-secret'
    a.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
    books_mod.register_routes(a)
    c = a.test_client()
    with c.session_transaction() as s:
        s['parent_auth'] = True
    return c


def _epub(title: str, body: str) -> bytes:
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:identifier id="bid">urn:uuid:{abs(hash(title))}</dc:identifier>
    <dc:language>en</dc:language>
  </metadata>
  <manifest><item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/></manifest>
  <spine><itemref idref="c1"/></spine>
</package>"""
    container = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"
    media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
    chapter = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<h1>Chapter 1</h1>
<p>{body}</p>
</body></html>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('mimetype', 'application/epub+zip')
        z.writestr('META-INF/container.xml', container)
        z.writestr('OEBPS/content.opf', opf)
        z.writestr('OEBPS/ch1.xhtml', chapter)
    return buf.getvalue()


_BODY = ' '.join(f'The small boy walked to school on Monday morning {i} times.' for i in range(10))


def test_import_stores_lexile_in_data_json(client):
    r = client.post('/api/book/import',
                    data={'epub': (io.BytesIO(_epub('Lexi Book', _BODY)), 'lexi.epub')},
                    content_type='multipart/form-data')
    assert r.status_code == 200 and r.get_json()['success'], r.get_json()

    row = get_db().execute(
        "SELECT data_json FROM books WHERE id='lexi_book'").fetchone()
    data = json.loads(row[0])
    assert data['lexile'] == books_mod.calc_lexile(data)
    assert 0 < data['lexile'] < 2001


def test_list_and_get_read_stored_lexile(client):
    """列表和详情接口返回的 lexile 与存储值一致 (不用家长重新扫全书)。"""
    r = client.post('/api/book/import',
                    data={'epub': (io.BytesIO(_epub('Lexi Two', _BODY)), 'lexi2.epub')},
                    content_type='multipart/form-data')
    assert r.get_json()['success'], r.get_json()

    listed = client.get('/api/books').get_json()['books']
    # 和 DB 里的存储值一致 (列表接口读到的是算好的,不再现场扫全书)
    stored = json.loads(get_db().execute(
        "SELECT data_json FROM books WHERE id='lexi_two'").fetchone()[0])['lexile']
    assert listed[0]['lexile'] == stored

    detail = client.get('/api/book/lexi_two').get_json()['book']
    assert detail['lexile'] == stored
