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
