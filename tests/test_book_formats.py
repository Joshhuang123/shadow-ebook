"""多格式导入的守护。

这一轮加的东西(EPUB 之外的格式)很容易被改坏,而且坏了很安静:
导入照样返回 success,书也进库了,只是**里面没有句子** ——
孩子打开是一页空白,家长只会觉得「这书有问题」。

所以这里守的是几件不变量:

1. 各种格式(TXT / PDF / DOCX / HTML)都要能转成**和 EPUB 一样**的结构
   {chapters:[{name, sentences}], cover, ...} —— 否则下游(查词/朗读/跟读)
   对不同格式导进来的书行为会不一样。
2. 转换失败必须给**能看懂**的原因,不是「导入失败: ValueError」。
3. 中文文件名不能被 secure_filename 削没了(「小王子.txt」→ 「.txt」)。
4. 中文正文要能切出句子 —— 原来的分句器只认 .!? 和「≥3 个空格分词」,
   一整段中文是 1 个「词」,直接被丢掉,中文书导入进来是空的。
5. 排版连字要还原 —— PDF 提取出来的是 U+FB01 之类,没装这些字形的字体
   会显示成方框。
"""
import io
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extensions import book_formats as bf          # noqa: E402
from extensions import books as books_mod          # noqa: E402


@pytest.fixture
def client(tmp_db):
    import importlib
    import app as app_module
    importlib.reload(app_module)
    return app_module.app.test_client()


TXT_EN = """The Little Prince

Chapter 1
When I was six years old, I saw a magnificent picture in a book about the Amazon jungle.
It was a picture of a green snake that was swallowing a beast.
I was so fascinated by it that I copied it in pencil, and tried to make it my own.

Chapter 2
The boa constrictor had swallowed the beast, and the picture showed him inside.
All my life I had kept that picture.
It is the story of the little prince that I want to tell you.
"""

TXT_ZH = """第一章 春天

从前有座山，山上有一棵树。树上住着一位老爷爷，他每天都很忙。
冬天快要结束了，老爷爷开始清理自己的身体。这需要很大力气。

第二章 乌云

有一天，他突然被一个声音吵醒了。声音很轻很细，他还没来得及看清。
"""


# === 格式转换器 ===

def test_txt_converts_to_book_structure():
    d = bf.convert(TXT_EN.encode('utf-8'), 'The Little Prince.txt')
    assert d['book'] == 'The Little Prince'
    assert d['id']
    assert len(d['chapters']) == 2
    for ch in d['chapters']:
        assert ch['name']
        assert ch['sentences'], '章节里必须有句子'
    assert d['chapters'][0]['name'].startswith('Chapter 1')
    assert d['source_format'] == '.txt'


def test_chinese_chapter_headings_are_kept():
    d = bf.convert(TXT_ZH.encode('utf-8'), '小王子.txt')
    names = ' '.join(c['name'] for c in d['chapters'])
    assert '第一章' in names, f'中文章节标题丢了: {names}'


def test_html_converts():
    html = ('<html><head><style>p{color:red}</style></head><body>'
            '<h1>Chapter 1</h1>'
            '<p>When I was six years old I saw a magnificent picture in a book.</p>'
            '<p>It was a picture of a green snake that was swallowing a beast.</p>'
            '<script>alert(1)</script>'
            '</body></html>')
    d = bf.convert(html.encode('utf-8'), 'story.html')
    total = sum(len(c['sentences']) for c in d['chapters'])
    assert total >= 1, 'HTML 没切出句子'
    joined = ' '.join(s for c in d['chapters'] for s in c['sentences'])
    assert 'alert(1)' not in joined, '<script> 内容混进正文了'
    assert 'color:red' not in joined, '<style> 内容混进正文了'


def test_docx_converts():
    docx = pytest.importorskip('docx')
    document = docx.Document()
    document.add_heading('Chapter 1', 1)
    document.add_paragraph('When I was six years old I saw a magnificent picture in a book.')
    document.add_paragraph('It was a picture of a green snake that was swallowing a beast.')
    buf = io.BytesIO()
    document.save(buf)
    d = bf.convert(buf.getvalue(), 'story.docx')
    assert sum(len(c['sentences']) for c in d['chapters']) >= 1


def test_pdf_converts():
    pytest.importorskip('pypdf')
    pdf_bytes = _make_text_pdf()
    d = bf.convert(pdf_bytes, 'story.pdf')
    assert sum(len(c['sentences']) for c in d['chapters']) >= 1


def test_scanned_pdf_is_rejected_with_actionable_message():
    """扫描版 PDF 提不出字 —— 必须说人话,不能给一本空书。"""
    pytest.importorskip('pypdf')
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (900, 1200), 'white')
    draw = ImageDraw.Draw(img)
    for y in range(0, 1200, 50):
        draw.rectangle([80, y, 820, y + 25], fill=(20, 20, 20))
    buf = io.BytesIO()
    img.save(buf, 'PDF')
    with pytest.raises(bf.ConversionError) as e:
        bf.convert(buf.getvalue(), 'scan.pdf')
    msg = str(e.value)
    assert '扫描' in msg and 'OCR' in msg, f'提示没说清怎么办: {msg}'


def test_unsupported_format_is_rejected():
    with pytest.raises(bf.ConversionError) as e:
        bf.convert(b'xx', 'book.cbr')
    assert '不支持' in str(e.value)


def test_oversized_file_is_rejected(monkeypatch):
    """超大的文件要在转换之前就被挡住,不然内存先炸。"""
    monkeypatch.setattr(bf, 'MAX_UPLOAD_BYTES', 10)
    with pytest.raises(bf.ConversionError) as e:
        bf.convert(b'x' * 100, 'a.txt')
    assert '太大' in str(e.value)


def test_empty_file_gives_clear_error():
    with pytest.raises(bf.ConversionError) as e:
        bf.convert(b'   \n\n  ', 'empty.txt')
    assert '文字' in str(e.value)


def test_ligatures_are_normalized():
    """PDF 里的排版连字要还原成普通字母,不然正文里是一堆方框。"""
    d = bf.convert('Chapter 1\nThe magniﬁcent ﬂy was not afraid at all of anything here.'.encode('utf-8'), 'x.txt')
    text = ' '.join(s for c in d['chapters'] for s in c['sentences'])
    assert 'ﬁ' not in text and 'ﬂ' not in text, f'连字没还原: {text}'
    assert 'magnificent' in text


def test_cover_is_generated_when_source_has_none():
    d = bf.convert(TXT_EN.encode('utf-8'), 'The Little Prince.txt')
    assert d['cover'], '没有封面的格式应该生成一张占位封面'
    assert d['cover'].startswith('/data/covers/')


# === 中文分句 ===

def test_chinese_text_is_split_into_sentences():
    """原来中文整段是 1 个「词」,被判成不合格直接丢掉。"""
    out = books_mod._split_sentences('从前有座山，山上有一棵树。树上住着一位老爷爷，他每天都很忙。')
    assert len(out) >= 2, f'中文没切成多句: {out}'


def test_english_splitting_is_unchanged():
    """纯英文的判定路径一个字没改 —— 同一本英文书用 EPUB 和 TXT 导入
    断句必须一致,否则孩子点词查义会时灵时不灵。"""
    assert books_mod._split_sentences('He sat down. She looked up.') == \
        ['He sat down.', 'She looked up.']


def test_english_abbreviation_still_protected():
    out = books_mod._split_sentences('Dr. Smith went home. Mrs. Lee stayed.')
    assert out == ['Dr. Smith went home.', 'Mrs. Lee stayed.']


def test_ligature_normalization_helper():
    assert books_mod._normalize_ligatures('aﬁbﬂc') == 'afibflc'


# === 导入路由 ===

def _login(client):
    r = client.post('/api/parent/login', json={'pin': '0000'})
    assert r.get_json().get('success')


def test_import_rejects_unsupported_format(client):
    _login(client)
    r = client.post('/api/book/import', data={'file': (io.BytesIO(b'x'), 'book.cbr')},
                    content_type='multipart/form-data')
    body = r.get_json()
    assert not body.get('success')
    assert '不支持' in body.get('error', '')


def test_import_txt_creates_readable_book(client, tmp_path):
    _login(client)
    r = client.post('/api/book/import',
                    data={'file': (io.BytesIO(TXT_EN.encode('utf-8')), 'The Little Prince.txt')},
                    content_type='multipart/form-data')
    body = r.get_json()
    assert body.get('success'), body
    assert body['total_chapters'] == 2
    assert body['total_sentences'] >= 4
    assert body['source_format'] == '.txt'

    # 导进来的书要真的能读:章节和句子都在
    got = client.get(f"/api/book/{body['book_id']}").get_json()
    book = got['book']
    assert book['chapters']
    assert any(ch['sentences'] for ch in book['chapters'])


def test_import_chinese_filename_keeps_extension(client):
    """secure_filename 会把中文全删掉 ——「小王子.txt」变成「.txt」,
    扩展名都没了,直接被判成不支持的格式。"""
    _login(client)
    r = client.post('/api/book/import',
                    data={'file': (io.BytesIO(TXT_ZH.encode('utf-8')), '小王子.txt')},
                    content_type='multipart/form-data')
    body = r.get_json()
    assert body.get('success'), body
    assert body['book_title'] == '小王子'
    assert body['source_format'] == '.txt'


def test_import_duplicate_returns_409(client):
    _login(client)

    def upload():
        # 每次都要新的 BytesIO —— 上传完 werkzeug 会把它关掉,复用会报
        # "I/O operation on closed file"
        return {'file': (io.BytesIO(TXT_EN.encode('utf-8')), 'Dup Book.txt')}

    assert client.post('/api/book/import', data=upload(),
                       content_type='multipart/form-data').get_json()['success']
    r = client.post('/api/book/import', data=upload(),
                    content_type='multipart/form-data')
    assert r.status_code == 409
    assert '已存在' in r.get_json().get('error', '')


def test_import_requires_parent_auth(client):
    r = client.post('/api/book/import',
                    data={'file': (io.BytesIO(TXT_EN.encode('utf-8')), 'x.txt')},
                    content_type='multipart/form-data')
    assert r.status_code == 401


def test_cover_route_is_registered():
    """封面路由曾经被 helper 挤到 register_routes 外面,永远 404,
    每一本书都掉进占位封面。这条钉住它。"""
    import app as app_module
    import importlib
    importlib.reload(app_module)
    rules = {str(r) for r in app_module.app.url_map.iter_rules()}
    assert '/data/covers/<path:filename>' in rules, '封面路由没注册,所有书都掉进占位封面'


def _make_text_pdf():
    """造一个真的文字版 PDF(带文本层,不是图片)。

    手写最小 PDF:PDF 头 + 5 个对象 + xref 表。
    用来验证「文字版 PDF 能被提取」这条路径 —— 扫描版(纯图片)
    走的是另一条分支(应该被拒绝并给出 OCR 提示)。
    """
    lines = [
        'Chapter 1',
        'When I was six years old I saw a magnificent picture in a book.',
        'It was a picture of a green snake that was swallowing a beast.',
    ]
    content = 'BT /F1 12 Tf 72 720 Td 14 TL\n'
    for ln in lines:
        esc = ln.replace('\\', r'\\').replace('(', r'\(').replace(')', r'\)')
        content += f'({esc}) Tj T*\n'
    content += 'ET\n'
    cb = content.encode('latin-1')
    objs = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R '
        b'/Resources << /Font << /F1 5 0 R >> >> >>',
        b'<< /Length ' + str(len(cb)).encode() + b' >>\nstream\n' + cb + b'\nendstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    ]
    out = bytearray(b'%PDF-1.4\n')
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f'{i} 0 obj\n'.encode() + o + b'\nendobj\n'
    xref = len(out)
    out += f'xref\n0 {len(objs) + 1}\n'.encode()
    out += b'0000000000 65535 f \n'
    for off in offsets:
        out += f'{off:010d} 00000 n \n'.encode()
    out += (f'trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n'
            f'startxref\n{xref}\n%%EOF\n').encode()
    return bytes(out)


# ============================================================
# DRM 检测
# ------------------------------------------------------------
# 「为什么我的书导不进来」的第一答案不是格式,是加密。
# 图书馆借的书(OverDrive/Libby 用 ACSM)、Kindle 买的(ADEPT)
# 文件结构完全合法、扩展名也是 .epub,但正文是加密的。
# 不提前拦下来的话,家长看到的是几百页之后一句「没读到正文」。
# ============================================================

def _epub_with(extra_files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('mimetype', 'application/epub+zip')
        z.writestr('META-INF/container.xml',
                   '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr('OEBPS/content.opf',
                   '<?xml version="1.0"?><package '
                   'xmlns="http://www.idpf.org/2007/opf" version="3.0">'
                   '<metadata/><manifest/><spine/></package>')
        z.writestr('OEBPS/ch.xhtml',
                   '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
                   '<p>Some text here that is long enough to count.</p></body></html>')
        for name, content in extra_files.items():
            z.writestr(name, content)
    return buf.getvalue()


def test_drm_epub_is_detected_acsm():
    """图书馆借的书(OverDrive/Libby)带 META-INF/sinf.xml。"""
    raw = _epub_with({'META-INF/sinf.xml': '<sinf/>'})
    import zipfile
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        kind = bf.detect_epub_drm(z.namelist(), read=lambda n: z.read(n))
    assert kind == 'acsm'


def test_drm_epub_is_detected_adept():
    raw = _epub_with({'META-INF/encryption.xml':
                       '<?xml version="1.0"?><encryption '
                       'xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
                       'Algorithm="http://ns.adobe.com/pdf/enc#RC"/>'})
    import zipfile
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        kind = bf.detect_epub_drm(z.namelist(), read=lambda n: z.read(n))
    assert kind == 'adept'


def test_font_obfuscation_is_not_mistaken_for_drm():
    """EPUB 的字体嵌入混淆也用 encryption.xml,但它不是 DRM。

    误判的话一大半正常 EPUB 会被当成带加密拒掉 —— 更糟。
    """
    raw = _epub_with({'META-INF/encryption.xml':
                       '<?xml version="1.0"?><encryption '
                       'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                       '<EncryptedData><EncryptionMethod '
                       'Algorithm="http://www.idpf.org/2008/embedding"/>'
                       '</EncryptedData></encryption>'})
    import zipfile
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        kind = bf.detect_epub_drm(z.namelist(), read=lambda n: z.read(n))
    assert kind is None, '字体混淆被误判成 DRM 了'


def test_drm_epub_import_is_rejected_with_actionable_message(client):
    _login(client)
    raw = _epub_with({'META-INF/sinf.xml': '<sinf/>'})
    r = client.post('/api/book/import',
                    data={'file': (io.BytesIO(raw), 'borrowed.epub')},
                    content_type='multipart/form-data')
    body = r.get_json()
    assert r.status_code == 400
    assert not body.get('success')
    assert body.get('drm') is True
    assert 'DRM' in body.get('error', '')
    # 提示里要告诉家长下一步怎么办,而不只是「失败了」
    assert '无 DRM' in body.get('error', '') or '没加密' in body.get('error', '')


def test_mobi_drm_flag_is_detected():
    """MOBI 头的 EXTH 里有 DRM 记录。"""
    import struct
    raw = bytearray(b'BOOKMOBI' + b'\x00' * 52)
    raw += b'EXTH'
    body = struct.pack('>II', 12, 1) + struct.pack('>II', 0x01, 4) + struct.pack('>I', 2)
    raw += body
    assert bf.detect_mobi_drm(bytes(raw)) is True
    # 改成 1(无 DRM)就不该判定
    raw2 = bytearray(raw)
    raw2[-4:] = struct.pack('>I', 1)
    assert bf.detect_mobi_drm(bytes(raw2)) is False


def test_mobi_extension_is_accepted():
    assert '.mobi' in bf.SUPPORTED_EXTENSIONS
    assert '.azw3' in bf.SUPPORTED_EXTENSIONS


# ============================================================
# 预览 + 章节选择
# ------------------------------------------------------------
# 「一本书 24 章,家长只想导其中几章」—— 版权页、目录、试读、
# 作者的「本书献给…」都不想要。所以导入前先看目录、勾选。
#
# 另外:预览时文件已经在服务端暂存了,导入时带 token 就行,
# 50MB 的 PDF 不用在局域网上传两遍。
# ============================================================

def test_preview_returns_chapters_without_writing(client):
    """预览只返回目录,**不入库**。"""
    _login(client)
    r = client.post('/api/book/import',
                    data={'file': (io.BytesIO(TXT_EN.encode('utf-8')),
                                   'The Little Prince.txt'),
                          'preview': 'true'},
                    content_type='multipart/form-data')
    body = r.get_json()
    assert body.get('success'), body
    assert body.get('preview') is True
    assert body.get('token')
    assert len(body['chapters']) == 2
    assert body['chapters'][0]['name'].startswith('Chapter 1')
    assert body['chapters'][0]['sentences'] >= 3
    # 库里不能有这本书
    assert client.get('/api/books').get_json().get('books') == []


def test_import_with_token_and_chapter_filter(client):
    """带 token + 章节下标 → 只导选中的那几章。"""
    _login(client)
    preview = client.post('/api/book/import',
                          data={'file': (io.BytesIO(TXT_EN.encode('utf-8')),
                                         'The Little Prince.txt'),
                                'preview': 'true'},
                          content_type='multipart/form-data').get_json()
    token = preview['token']

    r = client.post('/api/book/import', json={'token': token, 'chapters': [0]})
    body = r.get_json()
    assert body.get('success'), body
    assert body['total_chapters'] == 1, '只勾了一章,却导进去多章'
    assert body['total_sentences'] >= 3

    got = client.get(f"/api/book/{body['book_id']}").get_json()['book']
    assert len(got['chapters']) == 1


def test_import_with_token_and_no_selection_keeps_all(client):
    """一个章节都没选 = 全都要(而不是导一本空书)。"""
    _login(client)
    preview = client.post('/api/book/import',
                          data={'file': (io.BytesIO(TXT_EN.encode('utf-8')),
                                         'All Of It.txt'),
                                'preview': 'true'},
                          content_type='multipart/form-data').get_json()
    r = client.post('/api/book/import',
                    json={'token': preview['token'], 'chapters': []})
    body = r.get_json()
    assert body.get('success'), body
    assert body['total_chapters'] == 2


def test_expired_token_gives_clear_error(client):
    _login(client)
    r = client.post('/api/book/import', json={'token': 'not-a-real-token-1234'})
    assert r.status_code == 410
    assert '预览' in r.get_json().get('error', '')


def test_preview_requires_parent_auth(client):
    r = client.post('/api/book/import',
                    data={'file': (io.BytesIO(TXT_EN.encode('utf-8')), 'x.txt'),
                          'preview': 'true'},
                    content_type='multipart/form-data')
    assert r.status_code == 401


def test_staging_area_roundtrip():
    """暂存区:存进去能取回来,token 猜不出来,取完能删掉。"""
    from extensions import import_stage
    token = import_stage.stage(b'hello world', 'book.txt')
    raw, name = import_stage.get(token)
    assert raw == b'hello world'
    assert name == 'book.txt'
    import_stage.drop(token)
    assert import_stage.get(token) == (None, None)
    # 猜不出来的 token 取不到东西
    assert import_stage.get('zzzz-zzzz-zzzz') == (None, None)
    # 非法 token 直接挡掉
    assert import_stage.get('../../etc/passwd') == (None, None)


def test_staging_cleans_expired():
    """过期��暂存要被清掉,不然磁盘会被撑爆。"""
    import time
    from extensions import import_stage
    token = import_stage.stage(b'x' * 100, 'old.txt')
    # 把时间戳改到很久以前
    meta = import_stage._meta_path(token)
    info = __import__('json').loads(meta.read_text(encoding='utf-8'))
    info['ts'] = time.time() - import_stage.TTL_SECONDS - 60
    meta.write_text(__import__('json').dumps(info), encoding='utf-8')
    import_stage.cleanup_expired()
    assert import_stage.get(token) == (None, None)
