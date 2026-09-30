"""tests/test_book_delete_cleanup.py — 删书必须连封面一起删。

背景(2026-09-30):
    DELETE /api/book/<id> 只删了 books 表的一行,封面文件留在 data/covers/ 里。
    线上已积了 9 个无主封面(bleak_house / harry_potter_1 / percy_jackson_2 …),
    每一本对应的书早就不在了。

    封面文件名由标题推导(_save_cover: f'{_sanitize_book_id(title)}.{ext}'),
    所以按 book_id(= 同一个 sanitize 结果)glob 就能精确命中,不会误删别的书。
"""
import io
import json
import zipfile

import pytest

from extensions import books as books_mod
from extensions import db as db_mod

_JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 2048 + b'\xff\xd9'


def _epub(title: str) -> bytes:
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>A</dc:creator>
    <dc:identifier id="bid">urn:uuid:x</dc:identifier>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ci" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>"""
    container = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"
    media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
    nav = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<body><nav epub:type="toc"><ol><li><a href="ch1.xhtml">C1</a></li></ol></nav></body></html>"""
    ch = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>A sentence here. Another one.</p></body></html>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('mimetype', 'application/epub+zip')
        z.writestr('META-INF/container.xml', container)
        z.writestr('OEBPS/content.opf', opf)
        z.writestr('OEBPS/nav.xhtml', nav)
        z.writestr('OEBPS/ch1.xhtml', ch)
        z.writestr('OEBPS/cover.jpg', _JPEG)
    return buf.getvalue()


@pytest.fixture
def covers(tmp_db, monkeypatch):
    cdir = tmp_db / 'covers'
    cdir.mkdir()
    monkeypatch.setattr(books_mod, 'COVERS_DIR', cdir)
    return cdir


@pytest.fixture
def client(covers, clear_api_rate):
    from flask import Flask
    a = Flask(__name__)
    a.config['TESTING'] = True
    a.config['SECRET_KEY'] = 'test-secret'
    books_mod.register_routes(a)
    c = a.test_client()
    with c.session_transaction() as s:
        s['parent_auth'] = True
    return c


def _import(client, title):
    return client.post('/api/book/import',
                       data={'epub': (io.BytesIO(_epub(title)), 'x.epub')},
                       content_type='multipart/form-data')


def test_delete_removes_cover_file(client, covers):
    """删书后封面文件不该留在盘上。"""
    assert _import(client, 'Orphan Test Book').status_code == 200
    written = list(covers.glob('orphan_test_book.*'))
    assert len(written) == 1, f'导入阶段就该写出封面,实际 {written}'

    r = client.delete('/api/book/orphan_test_book')
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['success'] is True

    assert list(covers.glob('orphan_test_book.*')) == [], '封面文件成了无主孤儿'


def test_delete_keeps_other_books_covers(client, covers):
    """删 A 书不能顺手删掉 B 书的封面。"""
    _import(client, 'Keep Me Book')
    _import(client, 'Drop Me Book')
    assert list(covers.glob('keep_me_book.*'))
    assert list(covers.glob('drop_me_book.*'))

    assert client.delete('/api/book/drop_me_book').status_code == 200

    assert list(covers.glob('keep_me_book.*')), '误删了别的书的封面'
    assert list(covers.glob('drop_me_book.*')) == []


def test_delete_missing_book_is_404(client, covers):
    """不存在的书 → 404,且不能误删任何封面。"""
    other = covers / 'someone_elses.jpg'
    other.write_bytes(_JPEG)

    r = client.delete('/api/book/no_such_book')
    assert r.status_code == 404
    assert other.exists(), '404 路径不该碰封面目录'
