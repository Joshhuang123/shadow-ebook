"""tests/test_book_import_cover_guard.py — 重复导入不得污染已有书籍的封面。

背景(2026-09-30 修复的真实 bug):
    判重逻辑原本放在 EPUB 解析末尾,而封面早在 _save_cover() 就落盘了。
    同 book_id 第二次导入时,数据确实被 409 拦下没覆盖,但旧书的封面文件
    已经被新 EPUB 的封面盖掉 —— 旧书从此顶着新书的封面显示,而且没有任何提示。

本测试把这条路径钉死:同 book_id 二次导入 → 409,且封面文件字节不变。
"""
import io
import zipfile

import pytest

from extensions import books as books_mod


def _epub(title: str, cover_bytes: bytes, body: str) -> bytes:
    """造一个最小但合法的 EPUB:container.xml + OPF + TOC + 1 个章节 + 1 张封面。"""
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>Test Author</dc:creator>
    <dc:identifier id="bid">urn:uuid:{abs(hash(title))}</dc:identifier>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="cover-img" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/>
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
<body><nav epub:type="toc"><ol><li><a href="ch1.xhtml">Chapter 1</a></li></ol></nav></body>
</html>"""

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
        z.writestr('OEBPS/nav.xhtml', nav)
        z.writestr('OEBPS/ch1.xhtml', chapter)
        z.writestr('OEBPS/cover.jpg', cover_bytes)
    return buf.getvalue()


def _jpeg(marker: bytes) -> bytes:
    """造一段 >1000 字节的 JPEG 占位数据。

    必须过 _save_cover 的 `len(img_data) < 1000` 最小体积校验,否则会被当成
    空图直接丢弃,测的就不是封面逻辑了。这里不追求是合法 JPEG ——
    测试只比字节是否一致,不需要真能解码。
    """
    return b'\xff\xd8\xff\xe0' + marker + b'\x00' * 2048 + b'\xff\xd9'


@pytest.fixture
def covers(tmp_db, monkeypatch):
    """把 COVERS_DIR 指到临时目录,测试绝不碰 data/covers/。"""
    cdir = tmp_db / 'covers'
    cdir.mkdir()
    monkeypatch.setattr(books_mod, 'COVERS_DIR', cdir)
    return cdir


@pytest.fixture
def client(covers, clear_api_rate):
    """建 app + 已通过家长鉴权的 client。

    必须同一个 client 上开 session:Flask 的 session 存在 client 的 cookie jar 里,
    换一次 test_client() 就是全新会话,parent_auth 会丢。
    """
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


def _import(client, filename, data):
    return client.post(
        '/api/book/import',
        data={'epub': (io.BytesIO(data), filename)},
        content_type='multipart/form-data',
    )


_BODY = ' '.join(f'This is sentence number {i} in the book body.' for i in range(12))


def test_duplicate_import_does_not_overwrite_cover(client, covers):
    """同 book_id 二次导入:409,且旧书封面字节必须原样保留。"""
    cover_a = _jpeg(b'AAAAAAAA')
    cover_b = _jpeg(b'BBBBBBBB')

    r1 = _import(client, 'shared.epub', _epub('Shared Title', cover_a, _BODY))
    assert r1.status_code == 200, r1.get_json()
    body1 = r1.get_json()
    assert body1['success'] is True

    # 封面确实落盘了,后面才有得比
    written = list(covers.glob('shared_title.*'))
    assert len(written) == 1, f'预期写出 1 个封面文件,实际 {written}'
    assert written[0].read_bytes() == cover_a

    # 第二次:同 title → 同 book_id,应该 409
    r2 = _import(client, 'shared.epub', _epub('Shared Title', cover_b, _BODY))
    assert r2.status_code == 409, r2.get_json()
    assert r2.get_json()['success'] is False

    # 关键断言:封面没被第二本覆盖
    assert written[0].read_bytes() == cover_a, '重复导入把旧书封面覆盖了 —— 这就是被修的 bug'


def test_duplicate_import_does_not_touch_db_row(client, covers):
    """二次导入也不该改动已有书的数据正文。"""
    r1 = _import(client, 'dup.epub', _epub('Dup Book', _jpeg(b'CCCCCCCC'), _BODY))
    assert r1.status_code == 200, r1.get_json()

    from extensions.db import get_db
    before = get_db().execute(
        "SELECT data_json FROM books WHERE id='dup_book'").fetchone()[0]

    _import(client, 'dup.epub', _epub('Dup Book', _jpeg(b'DDDDDDDD'),
                                      'Completely different body text here.'))

    after = get_db().execute(
        "SELECT data_json FROM books WHERE id='dup_book'").fetchone()[0]
    assert before == after, '重复导入改动了已有书的数据'
