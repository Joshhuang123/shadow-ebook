"""Round 4 守护: EPUB 解析 helpers (抽出到 module-level 后, 单独跑快验).

测 _split_sentences / _is_chapter_heading / _find_content_opf_path 三件最容易回归的事:
  - 称谓缩写 (Mr. Mrs. Dr.) 不被误判成句末
  - 数字小数点 (3.14) 不被误判成句末
  - 'He sat down.' 不会被误判成标题
  - 走 spec 找 content.opf (不是硬编码 OEBPS/content.opf)
"""
import io
import zipfile

import pytest

from extensions.books import (
    _split_sentences,
    _is_chapter_heading,
    _find_content_opf_path,
    _find_cover_via_opf,
    _parse_opf_metadata,
    _parse_toc,
)


# === _split_sentences ===

def test_split_basic_two_sentences():
    """注意: <3 词的句子会被过滤 (设计如此, 避免单句 'Hi.' 之类).
    所以两个分句都得 ≥3 词。"""
    sents = _split_sentences("Hello there world. How are you today?")
    assert sents == ["Hello there world.", "How are you today?"]


def test_split_abbreviation_not_split():
    """Mr. Mrs. Dr. 后跟大写词, 不该当句末"""
    sents = _split_sentences("Dr. Smith went to the store. He bought milk.")
    assert sents == ["Dr. Smith went to the store.", "He bought milk."]


def test_split_decimal_not_split():
    """数字小数点不该当句末"""
    sents = _split_sentences("Pi is 3.14 today. The number is large.")
    assert sents == ["Pi is 3.14 today.", "The number is large."]


def test_split_initial_not_split():
    """'J. R. R. Tolkien' 风格首字母缩写不该当句末"""
    sents = _split_sentences("J. R. R. Tolkien wrote many books. He was English.")
    # 'J.' 'R.' 'R.' 都不是句末, 整段可能合并成一句; 至少不能切出单字母句子
    assert all(len(s.split()) >= 3 for s in sents)
    assert not any(len(s.strip()) == 1 for s in sents)


def test_split_drops_too_short():
    """太短 (<10 字符 / <3 词) 的片段被滤掉"""
    sents = _split_sentences("Hi. This is a real sentence with enough words. OK.")
    # 'Hi.' (< 10 chars) 和 'OK.' (< 10 chars) 都不该出现
    assert "Hi." not in sents
    assert "OK." not in sents
    assert any("real sentence" in s for s in sents)


# === _clean_text: 防 CSS / script / head 污染正文 (R9 bug 修复) ===

from extensions.books import _clean_text


def test_clean_text_strips_style_block():
    """<style>...</style> 内容 (含 CSS @page 规则) 不该出现在正文。
    用户现场证据: 一本扫描版 EPUB 章节 HTML 里 <style>@page { margin: 5pt }</style>
    之前 _clean_text 只剥 tag 留内容 → '@page { margin-top: 5.000000pt; }' 进了句子流
    """
    html = '''<html><head><style>@page { margin-bottom: 5.000000pt; margin-top: 5.000000pt; }
    body { font-family: serif; }</style></head><body><p>This is real text in the chapter body.</p></body></html>'''
    out = _clean_text(html)
    assert '@page' not in out
    assert 'font-family' not in out
    assert '5.000000pt' not in out
    assert 'real text' in out


def test_clean_text_strips_script_block():
    """<script>...</script> 里的 JS 源码不该进正文"""
    html = '<html><body><script>alert("xss");</script><p>Real body text here.</p></body></html>'
    out = _clean_text(html)
    assert 'alert' not in out
    assert 'xss' not in out
    assert 'Real body text' in out


def test_clean_text_strips_head_block():
    """<head> 整块 (含 <title>, <meta> 等) 不该进正文"""
    html = '<html><head><title>Some Book Title</title><meta charset="utf-8"></head><body><p>Body content.</p></body></html>'
    out = _clean_text(html)
    assert 'Some Book Title' not in out
    assert 'utf-8' not in out
    assert 'Body content' in out


def test_clean_text_strips_html_comments():
    """<!-- ... --> 注释不该进正文"""
    html = '<html><body><!-- TODO: fix this later --><p>Visible text only.</p></body></html>'
    out = _clean_text(html)
    assert 'TODO' not in out
    assert 'fix this' not in out
    assert 'Visible text' in out


def test_clean_text_preserves_real_body():
    """正常 <p>/<h1>/<span> 的内容该保留"""
    html = '<p>First sentence here.</p><h1>Chapter 1</h1><p>Second <span>sentence</span> here.</p>'
    out = _clean_text(html)
    assert 'First sentence' in out
    assert 'Chapter 1' in out
    assert 'Second sentence' in out


def test_clean_text_unescapes_entities():
    """&amp; &lt; &quot; 等该解 entity"""
    html = '<p>Tom &amp; Jerry &lt;3 &quot;cheese&quot;</p>'
    out = _clean_text(html)
    assert 'Tom & Jerry' in out
    assert '<3' in out
    assert '"cheese"' in out


# === _is_chapter_heading ===

def test_heading_chapter_one():
    assert _is_chapter_heading("Chapter 1") is True


def test_heading_part_roman():
    assert _is_chapter_heading("Part IV") is True


def test_heading_prologue():
    assert _is_chapter_heading("Prologue") is True


def test_heading_short_no_punct():
    """≤5 词无标点 → 标题"""
    assert _is_chapter_heading("The Beginning") is True


def test_heading_rejects_long_sentence():
    """旧版会把 'He sat down.' 误判, 新版必须拒绝"""
    assert _is_chapter_heading("He sat down.") is False


def test_heading_rejects_too_long():
    """80 字符以上 → 不是标题"""
    long_text = "This is a very long heading that goes on and on and on for many many words"
    assert _is_chapter_heading(long_text) is False


def test_heading_rejects_too_many_words():
    """8 词以上 (无标点) → 不是标题"""
    assert _is_chapter_heading("The boy who lived under the stairs") is False


def test_heading_rejects_empty():
    assert _is_chapter_heading("") is False
    assert _is_chapter_heading("   ") is False


# === _find_content_opf_path ===

def _make_epub(files: dict) -> zipfile.ZipFile:
    """files: {arcname: bytes}"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    buf.seek(0)
    return zipfile.ZipFile(buf, 'r')


def test_find_opf_standard_oebps():
    """最常见布局: OEBPS/content.opf"""
    zf = _make_epub({
        'META-INF/container.xml': (
            b'<?xml version="1.0"?>'
            b'<container version="1.0">'
            b'<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
            b'</rootfiles></container>'
        ),
    })
    assert _find_content_opf_path(zf) == 'OEBPS/content.opf'


def test_find_opf_nested_path():
    """非标准路径 (如 EPUB3 root 文件可能更深)"""
    zf = _make_epub({
        'META-INF/container.xml': (
            b'<?xml version="1.0"?>'
            b'<container><rootfiles>'
            b'<rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/>'
            b'</rootfiles></container>'
        ),
    })
    assert _find_content_opf_path(zf) == 'EPUB/package.opf'


def test_find_opf_missing_container_returns_empty():
    """没 META-INF/container.xml → 视为非 EPUB"""
    zf = _make_epub({'random.txt': b'not an epub'})
    assert _find_content_opf_path(zf) == ''


def test_find_opf_malformed_returns_empty():
    """container.xml 存在但内容残缺, 不该 crash"""
    zf = _make_epub({'META-INF/container.xml': b'<garbage'})
    assert _find_content_opf_path(zf) == ''


# === _find_cover_via_opf (Round 6: 走 spec 找封面) ===

_OPF_WITH_COVER = b'''<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata>
    <meta name="cover" content="cover-img"/>
    <dc:title>Test</dc:title>
  </metadata>
  <manifest>
    <item id="cover-img" href="images/cover.jpg" media-type="image/jpeg"/>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="ch1"/></spine>
</package>'''


def test_find_cover_via_opf_basic():
    """标准 EPUB 3: <meta name="cover" content="cover-img"> → manifest href"""
    zf = _make_epub({
        'META-INF/container.xml': b'<container><rootfiles><rootfile full-path="content.opf"/></rootfiles></container>',
        'content.opf': _OPF_WITH_COVER,
    })
    assert _find_cover_via_opf(zf, 'content.opf') == 'images/cover.jpg'


def test_find_cover_via_opf_nested_opf():
    """opf 在子目录时, href 需拼接 opf_dir 才是正确 arcname"""
    zf = _make_epub({
        'META-INF/container.xml': b'<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        'OEBPS/content.opf': _OPF_WITH_COVER.replace(b'images/cover.jpg', b'cover.jpg'),
    })
    assert _find_cover_via_opf(zf, 'OEBPS/content.opf') == 'OEBPS/cover.jpg'


def test_find_cover_via_opf_no_meta_returns_empty():
    """没有 <meta name="cover"> → 降级给 import_book 走文件名 fallback"""
    zf = _make_epub({
        'content.opf': b'<?xml version="1.0"?><package><manifest><item id="x" href="x.jpg"/></manifest></package>',
    })
    assert _find_cover_via_opf(zf, 'content.opf') == ''


def test_find_cover_via_opf_id_mismatch_returns_empty():
    """meta 指向 manifest 里不存在的 id (EPUB 制作 bug) → 返空, 不 crash"""
    zf = _make_epub({
        'content.opf': b'<?xml version="1.0"?><package><metadata><meta name="cover" content="ghost"/></metadata><manifest><item id="real" href="real.jpg"/></manifest></package>',
    })
    assert _find_cover_via_opf(zf, 'content.opf') == ''


def test_find_cover_via_opf_empty_path_returns_empty():
    """opf_path 为空 → 返空 (调用方会走文件名 fallback)"""
    assert _find_cover_via_opf(_make_epub({}), '') == ''


# === _parse_opf_metadata (R9: 提取出版信息) ===

_FULL_OPF = b'''<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">
  <metadata>
    <dc:title>Harry Potter and the Philosopher's Stone</dc:title>
    <dc:creator id="creator">J.K. Rowling</dc:creator>
    <dc:publisher>Scholastic</dc:publisher>
    <dc:date>1997-06-26</dc:date>
    <dc:language>en</dc:language>
    <dc:description>A young wizard discovers his heritage.</dc:description>
    <dc:identifier id="isbn">urn:isbn:9780439362139</dc:identifier>
    <dc:subject>Fantasy</dc:subject>
    <dc:subject>Children</dc:subject>
    <dc:rights>Copyright J.K. Rowling</dc:rights>
    <meta name="cover" content="cover-img"/>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="ch1"/></spine>
</package>'''


def test_parse_opf_metadata_full():
    """全字段 OPF 一次性提全: title/creator/publisher/year/language/description/identifier/subjects[]/rights"""
    zf = _make_epub({'content.opf': _FULL_OPF})
    meta = _parse_opf_metadata(zf, 'content.opf')
    assert meta['title'] == "Harry Potter and the Philosopher's Stone"
    assert meta['creator'] == 'J.K. Rowling'
    assert meta['publisher'] == 'Scholastic'
    assert meta['date'] == '1997-06-26'
    assert meta['year'] == 1997
    assert meta['language'] == 'en'
    assert meta['description'].startswith('A young wizard')
    assert meta['identifier'] == 'urn:isbn:9780439362139'
    assert meta['subjects'] == ['Fantasy', 'Children']
    assert meta['rights'] == 'Copyright J.K. Rowling'


def test_parse_opf_metadata_year_only_date():
    """有些 EPUB date 只写 '1997' 或 '1997-00-00', 都能解出 year=1997"""
    zf = _make_epub({'content.opf': b'<package><metadata><dc:date>1997</dc:date></metadata></package>'})
    meta = _parse_opf_metadata(zf, 'content.opf')
    assert meta['date'] == '1997'
    assert meta['year'] == 1997


def test_parse_opf_metadata_missing_fields():
    """缺字段时返 None / [], 不该 crash"""
    zf = _make_epub({'content.opf': b'<package><metadata><dc:title>Only Title</dc:title></metadata></package>'})
    meta = _parse_opf_metadata(zf, 'content.opf')
    assert meta['title'] == 'Only Title'
    assert meta['creator'] is None
    assert meta['subjects'] == []
    assert meta['year'] is None


def test_parse_opf_metadata_no_metadata_block():
    """没 <metadata> 块 → 返空 dict, 不该 crash"""
    zf = _make_epub({'content.opf': b'<package><manifest/></package>'})
    assert _parse_opf_metadata(zf, 'content.opf') == {}


def test_parse_opf_metadata_no_opf_path():
    """opf_path 为空 → 返空 dict"""
    assert _parse_opf_metadata(_make_epub({}), '') == {}


# === _parse_toc (R9: 真 TOC 解析, NCX 优先, nav 兜底) ===

_NCX = b'''<?xml version="1.0"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="urn:uuid:abc"/></head>
  <docTitle><text>Book</text></docTitle>
  <navMap>
    <navPoint id="ch1" playOrder="1">
      <navLabel><text>Chapter 1: The Boy Who Lived</text></navLabel>
      <content src="ch1.xhtml"/>
    </navPoint>
    <navPoint id="ch2" playOrder="2">
      <navLabel><text>Chapter 2: The Vanishing Glass</text></navLabel>
      <content src="ch2.xhtml#anchor"/>
    </navPoint>
    <navPoint id="ch3" playOrder="3">
      <navLabel><text>Chapter 3: The Letters from No One</text></navLabel>
      <content src="ch3.xhtml"/>
    </navPoint>
  </navMap>
</ncx>'''


def test_parse_toc_ncx_basic():
    """NCX 格式 (EPUB 2): <navPoint><navLabel><text>TITLE</text></navLabel><content src="href"/></navPoint>"""
    zf = _make_epub({
        'content.opf': (
            b'<?xml version="1.0"?><package><manifest>'
            b'<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            b'</manifest><spine toc="ncx"/></package>'
        ),
        'toc.ncx': _NCX,
    })
    toc = _parse_toc(zf, 'content.opf')
    assert len(toc) == 3
    assert toc[0]['title'] == 'Chapter 1: The Boy Who Lived'
    assert toc[0]['href'] == 'ch1.xhtml'
    assert toc[1]['title'] == 'Chapter 2: The Vanishing Glass'
    # anchor 被剥掉 (我们用整页匹配, 不要 anchor 干扰)
    assert toc[1]['href'] == 'ch2.xhtml'
    assert toc[2]['title'] == 'Chapter 3: The Letters from No One'


def test_parse_toc_ncx_in_subdir():
    """NCX 在子目录 (OEBPS/toc.ncx) 时, manifest 的 href 需拼接 opf_dir"""
    zf = _make_epub({
        'META-INF/container.xml': b'<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        'OEBPS/content.opf': (
            b'<?xml version="1.0"?><package><manifest>'
            b'<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            b'</manifest><spine toc="ncx"/></package>'
        ),
        'OEBPS/toc.ncx': _NCX,
    })
    toc = _parse_toc(zf, 'OEBPS/content.opf')
    assert len(toc) == 3
    assert toc[0]['href'] == 'ch1.xhtml'


def test_parse_toc_nav_epub3():
    """EPUB 3 nav: <nav epub:type="toc"><ol><li><a href="x">Title</a></li></ol></nav>"""
    nav_html = b'''<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <body>
    <nav epub:type="toc">
      <h1>Table of Contents</h1>
      <ol>
        <li><a href="ch1.xhtml">Chapter 1: Beginnings</a></li>
        <li><a href="ch2.xhtml">Chapter 2: Journeys</a></li>
      </ol>
    </nav>
  </body>
</html>'''
    zf = _make_epub({
        'content.opf': b'<?xml version="1.0"?><package><manifest/></package>',
        'nav.xhtml': nav_html,
    })
    toc = _parse_toc(zf, 'content.opf')
    assert len(toc) == 2
    assert toc[0] == {'title': 'Chapter 1: Beginnings', 'href': 'ch1.xhtml', 'level': 0}
    assert toc[1]['title'] == 'Chapter 2: Journeys'


def test_parse_toc_no_toc_returns_empty():
    """既没 NCX 也没 nav → 返 [], 调用方降级到正则猜"""
    zf = _make_epub({
        'content.opf': b'<?xml version="1.0"?><package><manifest/></package>',
    })
    assert _parse_toc(zf, 'content.opf') == []


def test_parse_toc_no_opf_path():
    """opf_path 为空 → 返 []"""
    assert _parse_toc(_make_epub({}), '') == []
