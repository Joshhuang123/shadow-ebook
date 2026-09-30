"""
Owns: book metadata, book import (EPUB parsing), book list cache, book cover serving,
lexile estimation, secure book_id validation (path-traversal defense).
Does NOT own: TTS for book sentences (tts.py), parent stats (parent_data.py), DB layer (db.py).

Phase 3a: books 改走 SQLite (data/shadow.db),原 data/books/*.json 在首次启动时自动迁入,
        备份在 data/books.migrated-<ts>/ 留 30 天。
"""
import hashlib
import io
import json
import logging
import os
import re
import html
import time
import zipfile
from pathlib import Path
from flask import abort, jsonify, request, send_from_directory, session
from werkzeug.utils import secure_filename

from extensions.auth import require_parent_auth, _api_rate_limit_ok
from extensions.db import get_db, DB_PATH


logger = logging.getLogger(__name__)


# === 路径穿越防御: book_id 只能含字母数字下划线连字符 ===
BOOK_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')  # 防御 + URL/路径友好的硬上限
COVERS_DIR = Path(__file__).resolve().parent.parent / 'data' / 'covers'
COVER_URL_PREFIX = '/data/covers/'  # API 响应里 cover 字段的前缀, 反代改这里就能改


def is_valid_book_id(book_id):
    return bool(book_id and BOOK_ID_PATTERN.match(book_id))


# === debug 端点开关 ===
# 不能写成 `if os.environ.get('SHADOW_DEBUG'):` —— 那样 SHADOW_DEBUG=0
# (非空字符串) 在 Python 里是 truthy,等于把 debug 打开了。这是个经典坑。
_DEBUG_OFF = {'0', 'false', 'no', 'off', ''}


def _debug_enabled() -> bool:
    return os.environ.get('SHADOW_DEBUG', '').strip().lower() not in _DEBUG_OFF


# === EPUB 解析 helper (Round 4: 从 import_book 抽出来好测试) ===

def _clean_text(raw_html: str) -> str:
    """HTML → 纯文本。

    处理顺序 (顺序很重要):
      1) 删 <head>/<style>/<script>...</...> 整块 (含内容) — 否则 CSS @page 规则、
         <script> 源码、<title> 等会污染正文 (e.g. '@page { margin-top: 5pt }' 出现在句子流)
      2) 删 HTML 注释 <!-- ... -->
      3) 删剩余 tag (保留内容) — 应对 <p>/<span>/<h1> 等正常标签
      4) 解 entity
      5) 折叠空白
    """
    text = raw_html
    text = re.sub(r'<(head|style|script|noscript)[^>]*>.*?</\1>', ' ', text, flags=re.S | re.I)
    text = re.sub(r'<!--.*?-->', ' ', text, flags=re.S)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


_SENT_ABBREV = re.compile(r'\b(Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|Mt|vs|etc)\.')
_SENT_INITIAL = re.compile(r'\b([A-Z])\.')
_SENT_DECIMAL = re.compile(r'(\d)\.(\d)')


# === 解析质量审计 (R9 fixup 后, 用来发现尚未修掉的脏数据) ===
# 这些 pattern 都基于 _clean_text 之后的纯文本, 用来扫历史 import 残留
_AUDIT_CSS = re.compile(
    r'@page|@font-face|font-family|margin\s*:|padding\s*:|'
    r'background\s*:|color\s*:|[\.\#][a-zA-Z][\w-]*\s*\{|'
    r'<!\[CDATA|\}\s*\.\s*[a-z]'
)
_AUDIT_PAGENUM = re.compile(r'(?:\b\d{1,4}\b[\s,.-]*){3,}')
_AUDIT_SHORT_CHARS = 10  # < 10 字符的句子算"短到可疑"


def _audit_chapter(chapter: dict) -> dict:
    """对单章做解析质量审计, 返回 issue 计数和样本。"""
    sentences = chapter.get('sentences', []) or []
    text_list = [s if isinstance(s, str) else (s.get('text', '') if isinstance(s, dict) else '') for s in sentences]

    short_sents = [t for t in text_list if 0 < len(t.strip()) < _AUDIT_SHORT_CHARS]
    css_sents = [t for t in text_list if _AUDIT_CSS.search(t)]
    pagenum_sents = [t for t in text_list if _AUDIT_PAGENUM.search(t)]

    # 连续 2 句以上完全相同 (页眉页脚特征)
    repeated_groups = []
    i = 0
    while i < len(text_list):
        t = text_list[i].strip()
        if not t:
            i += 1
            continue
        j = i + 1
        while j < len(text_list) and text_list[j].strip() == t:
            j += 1
        if j - i >= 2 and len(t) > 5:
            repeated_groups.append({"text": t[:120], "occurrences": j - i})
        i = j

    return {
        "title": chapter.get('name', chapter.get('title', '')),
        "sentence_count": len(sentences),
        "short_sentence_count": len(short_sents),
        "short_sentence_samples": [s[:100] for s in short_sents[:3]],
        "css_residue_count": len(css_sents),
        "css_residue_samples": [s[:120] for s in css_sents[:3]],
        "pagenum_candidate_count": len(pagenum_sents),
        "pagenum_candidate_samples": [s[:120] for s in pagenum_sents[:3]],
        "repeated_count": len(repeated_groups),
        "repeated_samples": repeated_groups[:3],
    }
_SENT_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\'(])')


def _split_sentences(text: str) -> list:
    """智能分句: 避开称谓缩写 / 国家缩写 / 数字小数点 / 省略号。返回 ≥10 字符且 ≥3 词的句子。"""
    PLACEHOLDER = '\x00'
    text = _SENT_ABBREV.sub(r'\1' + PLACEHOLDER, text)
    text = _SENT_INITIAL.sub(r'\1' + PLACEHOLDER, text)
    text = _SENT_DECIMAL.sub(r'\1' + PLACEHOLDER + r'\2', text)
    text = text.replace('...', PLACEHOLDER * 3)
    parts = _SENT_SPLIT.split(text)
    sentences = []
    for p in parts:
        p = p.strip().replace(PLACEHOLDER, '.').strip('"\' ')
        if len(p) > 10 and len(p.split()) >= 3:
            sentences.append(p)
    return sentences


_HEADING_PATTERN = re.compile(
    r'^(chapter|part|prologue|epilogue|book|act|scene)\s+(\d+|[ivxlcdm]+)\b',
    re.I,
)


def _is_chapter_heading(text: str) -> bool:
    """判断 text 是否像章节标题。

    Round 4 收紧: 原来只看 "短 + 词少", 会把 'He sat down.' 误判成标题。
    新规则:
      - 太长 (>80 字符 / >8 词): 不是
      - 以句号结尾 + 不是 'Chapter N.' 句式: 不是 (普通句子)
      - 匹配 'Chapter N' / 'Part N' / 'Prologue' / 'Epilogue' 等: 是
      - 短 (≤5 词) + 无句末标点: 是 (类似 'The Beginning')
    """
    t = text.strip()
    if not t or len(t) > 80:
        return False
    word_count = len(t.split())
    if word_count > 8:
        return False
    if _HEADING_PATTERN.match(t):
        return True
    if word_count <= 5 and not t.endswith(('.', '!', '?')):
        return True
    return False


_CONTAINER_ROOTFILE = re.compile(r'<rootfile[^>]+full-path=["\']([^"\']+)["\']')
_OPF_ITEMREF = re.compile(r'<itemref[^>]+idref=["\']([^"\']+)["\']')
# manifest item 必须与属性顺序无关。
# 历史 bug(2026-09-30): 原来是 <item[^>]+id="..."[^>]+href="...">,强制 id 出现在 href 之前。
# 真实 EPUB(zlib 上的商业书,如 magic tree house 29)写的是
#   <item href="OEBPS/..._c001_r1.htm" id="c001" media-type="..."/>
# 结果整本 manifest 一条都匹配不上 → spine 解析返回空 → 降级 sorted(html_files)
# → 一本 20 多章的真书被压成 1 章 846 句。
_OPF_ITEM_TAG = re.compile(r'<item\b[^>]*>', re.I)
_OPF_ATTR_ID = re.compile(r'\bid=["\']([^"\']*)["\']', re.I)
_OPF_ATTR_HREF = re.compile(r'\bhref=["\']([^"\']*)["\']', re.I)


def _opf_items(opf: str) -> list:
    """从 OPF 文本抽 manifest 的 (id, href) 列表,与属性书写顺序无关。"""
    items = []
    for tag in _OPF_ITEM_TAG.findall(opf):
        m_id = _OPF_ATTR_ID.search(tag)
        m_href = _OPF_ATTR_HREF.search(tag)
        if m_id and m_href:
            items.append((m_id.group(1), m_href.group(1)))
    return items
_OPF_ITEMREF = re.compile(r'<itemref\b[^>]*>', re.I)
_OPF_ATTR_IDREF = re.compile(r'\bidref=["\']([^"\']*)["\']', re.I)
_OPF_META_TAG = re.compile(r'<meta\b[^>]*>', re.I)
_OPF_ATTR_NAME = re.compile(r'\bname=["\']([^"\']*)["\']', re.I)
_OPF_ATTR_CONTENT = re.compile(r'\bcontent=["\']([^"\']*)["\']', re.I)
# EPUB 3 用 manifest item 的 properties="cover-image" 声明封面,不再用 <meta name="cover">。
# 历史 bug: 只认 EPUB 2 的 meta,EPUB 3(现在的主流)一律导不出封面。
# 同样不能依赖属性顺序 —— 和 _opf_items 一样按 tag 逐个看。
_OPF_ATTR_PROPS = re.compile(r'\bproperties=["\']([^"\']*)["\']', re.I)


def _opf_cover_meta_id(opf: str) -> str:
    """读 <meta name="cover" content="..."> 的 content 值。

    同样不能依赖属性顺序:真实 EPUB 里存在 <meta content="cover-image" name="cover"/>
    这种字母序写法,要求 name 在 content 前的正则会直接漏掉。
    """
    for tag in _OPF_META_TAG.findall(opf):
        m_name = _OPF_ATTR_NAME.search(tag)
        if not m_name or m_name.group(1).strip().lower() != 'cover':
            continue
        m_content = _OPF_ATTR_CONTENT.search(tag)
        if m_content:
            return m_content.group(1).strip()
    return ''
# OPF metadata 提取 (dc:* 命名空间元素, 包在 <metadata>...</metadata> 里)
_DC_TITLE = re.compile(r'<dc:title[^>]*>([^<]*)</dc:title>', re.I)
_DC_CREATOR = re.compile(r'<dc:creator[^>]*>([^<]*)</dc:creator>', re.I)
_DC_PUBLISHER = re.compile(r'<dc:publisher[^>]*>([^<]*)</dc:publisher>', re.I)
_DC_DATE = re.compile(r'<dc:date[^>]*>([^<]*)</dc:date>', re.I)
_DC_LANGUAGE = re.compile(r'<dc:language[^>]*>([^<]*)</dc:language>', re.I)
_DC_DESCRIPTION = re.compile(r'<dc:description[^>]*>([^<]*)</dc:description>', re.I)
_DC_IDENTIFIER = re.compile(r'<dc:identifier[^>]*>([^<]*)</dc:identifier>', re.I)
_DC_SUBJECT = re.compile(r'<dc:subject[^>]*>([^<]*)</dc:subject>', re.I)
_DC_RIGHTS = re.compile(r'<dc:rights[^>]*>([^<]*)</dc:rights>', re.I)


def _find_content_opf_path(zf) -> str:
    """按 EPUB spec 走: META-INF/container.xml → rootfile full-path → 真正的 content.opf。
    找不到返回 '' (调用方降级到 sorted(html_files))。"""
    try:
        container = zf.read('META-INF/container.xml').decode('utf-8', errors='ignore')
    except KeyError:
        return ''
    m = _CONTAINER_ROOTFILE.search(container)
    return m.group(1) if m else ''


def _parse_spine_order(zf, opf_path: str) -> list:
    """从 content.opf 提取 spine 顺序 (chapter href 数组)。失败返回 []。"""
    if not opf_path:
        return []
    try:
        opf = zf.read(opf_path).decode('utf-8', errors='ignore')
    except KeyError:
        return []
    # 同样按 tag 逐个取 idref,不依赖 <itemref> 内部属性顺序
    spine_ids = []
    for tag in _OPF_ITEMREF.findall(opf):
        m = _OPF_ATTR_IDREF.search(tag)
        if m:
            spine_ids.append(m.group(1))
    id_to_file = dict(_opf_items(opf))
    # opf_path 可能带子目录 (如 OEBPS/content.opf), href 是相对路径
    opf_dir = opf_path.rsplit('/', 1)[0] + '/' if '/' in opf_path else ''
    return [opf_dir + id_to_file[sid] for sid in spine_ids if sid in id_to_file]


def _find_cover_via_opf(zf, opf_path: str) -> str:
    """走 EPUB spec 找封面。两条路,先新后旧:

    1. EPUB 3:manifest item 带 properties="cover-image" → 直接取它的 href
    2. EPUB 2:<meta name="cover" content="item_id"> → manifest id → href

    找不到返回 ''。比文件名猜更准 (尤其对不按 cover.jpg 命名的书)。
    """
    if not opf_path:
        return ''
    try:
        opf = zf.read(opf_path).decode('utf-8', errors='ignore')
    except KeyError:
        return ''

    opf_dir = opf_path.rsplit('/', 1)[0] + '/' if '/' in opf_path else ''

    # 1) EPUB 3 properties="cover-image"
    for tag in _OPF_ITEM_TAG.findall(opf):
        props = _OPF_ATTR_PROPS.search(tag)
        if props and 'cover-image' in props.group(1).lower().split():
            m_href = _OPF_ATTR_HREF.search(tag)
            if m_href:
                return opf_dir + m_href.group(1)

    # 2) EPUB 2 <meta name="cover" content="item_id">
    cover_id = _opf_cover_meta_id(opf)
    if not cover_id:
        return ''
    for item_id, href in _opf_items(opf):
        if item_id == cover_id:
            return opf_dir + href
    return ''


def _sanitize_book_id(raw: str) -> str:
    """sanitize 兜底: 全是非 ASCII / sanitize 后太短(<4)或全是下划线时,用 md5 短哈希代替。

    历史 bug: 中文书名 sanitize 后变全下划线 + 数字 (e.g. `____2022____`),
    现在 fallback 到 `book_<hash8>`, 既稳定又不依赖 sanitize 后字符集。
    """
    s = re.sub(r'[^a-zA-Z0-9_-]', '_', raw.lower()).strip('_')
    if len(s) < 4 or s.replace('_', '') == '':
        return f'book_{hashlib.md5(raw.encode()).hexdigest()[:8]}'
    return s


def _cover_url(cover_path: str | None) -> str | None:
    """DB 里 cover 字段 → API 响应里给前端的完整 URL。

    兼容两代格式:
      - 新 (R11+): 'covers/xxx.jpeg' → '/data/covers/xxx.jpeg'
      - 旧: '/data/covers/xxx.jpeg' → 原样返回
    这样迁移期混存也没事, 反代改 COVER_URL_PREFIX 一处即可。
    """
    if not cover_path:
        return None
    if cover_path.startswith('/'):
        return cover_path
    return COVER_URL_PREFIX + cover_path


def _save_cover(zf, book_title: str, arcname: str) -> str:
    """从 zipfile 里把 arcname 对应的图片写到 covers 目录, 返回 web path (/data/covers/xxx)。
    失败 (图片不存在 / 太小 / 写盘出错) 返回 ''。"""
    try:
        img_data = zf.read(arcname)
    except KeyError:
        return ''
    if len(img_data) < 1000:
        return ''
    try:
        COVERS_DIR.mkdir(parents=True, exist_ok=True)
        book_id_for_cover = _sanitize_book_id(book_title)
        ext = arcname.rsplit('.', 1)[-1].lower()
        # 仅允许已知图片后缀, 防 arcname='evil.html' 时被写成 .html 文件
        if ext not in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
            return ''
        cover_filename = f'{book_id_for_cover}.{ext}'
        cover_path_full = COVERS_DIR / cover_filename
        with open(cover_path_full, 'wb') as f:
            f.write(img_data)
        logger.info(f'封面已提取: {cover_filename}')
        # R11: 存相对路径 'covers/xxx', API 响应时拼前缀
        return f'covers/{cover_filename}'
    except OSError as e:
        logger.warning(f'写封面失败 {arcname}: {e}')
        return ''


def _parse_opf_metadata(zf, opf_path: str) -> dict:
    """从 content.opf 解析 Dublin Core metadata。
    返回 {title, creator, publisher, date, language, description, identifier, subjects[], rights}。
    字段缺失时为 None (subjects 为 []) — 调用方用 .get() 安全。"""
    if not opf_path:
        return {}
    try:
        opf = zf.read(opf_path).decode('utf-8', errors='ignore')
    except KeyError:
        return {}
    # 只在 <metadata>...</metadata> 范围内搜, 避免误中 <meta name="cover">
    m = re.search(r'<metadata[^>]*>(.*?)</metadata>', opf, re.S | re.I)
    if not m:
        return {}
    md = m.group(1)

    def _first(pattern):
        mm = pattern.search(md)
        return mm.group(1).strip() if mm else None

    date_str = _first(_DC_DATE)
    # date 可能是 '2020-09-15T00:00:00Z' 或 '2020' 或 'September 2020', 简化取前 4 位年份
    year = None
    if date_str:
        ym = re.match(r'(\d{4})', date_str)
        if ym:
            year = int(ym.group(1))

    return {
        'title': _first(_DC_TITLE),
        'creator': _first(_DC_CREATOR),
        'publisher': _first(_DC_PUBLISHER),
        'date': date_str,
        'year': year,
        'language': _first(_DC_LANGUAGE),
        'description': _first(_DC_DESCRIPTION),
        'identifier': _first(_DC_IDENTIFIER),
        'subjects': [s.strip() for s in _DC_SUBJECT.findall(md) if s.strip()],
        'rights': _first(_DC_RIGHTS),
    }


# === TOC 解析: NCX (EPUB 2) + nav (EPUB 3) ===
_NCX_MEDIA = 'application/x-dtbncx+xml'
_NAV_EPUB_TYPE = re.compile(r'<nav[^>]+epub:type=["\']toc["\']', re.I)
_NCX_NAVPOINT = re.compile(
    r'<navPoint[^>]+id=["\']([^"\']+)["\'][^>]+playOrder=["\']([^"\']+)["\']',
    re.I,
)
_NCX_NAVLABEL_TEXT = re.compile(r'<navLabel[^>]*>.*?<text[^>]*>([^<]*)</text>', re.S | re.I)
_NCX_CONTENT_SRC = re.compile(r'<content[^>]+src=["\']([^"\']+)["\']', re.I)
# nav 格式: <li><a href="ch1.xhtml">Title</a></li>
_NAV_LI = re.compile(r'<li[^>]*>\s*<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>', re.I)


def _parse_toc(zf, opf_path: str) -> list:
    """从 content.opf 找 NCX / nav, 解析真 TOC。

    返回 [{title, href, level}] 按阅读顺序, level 0 = 顶级章节 (nav 暂都返 0, 不深嵌)。
    找不到 NCX 和 nav 都返 [], 调用方降级到正则猜章节。
    """
    if not opf_path:
        return []
    try:
        opf = zf.read(opf_path).decode('utf-8', errors='ignore')
    except KeyError:
        return []

    opf_dir = opf_path.rsplit('/', 1)[0] + '/' if '/' in opf_path else ''

    # 1) EPUB 2 NCX: 在 manifest 里找 media-type='application/x-dtbncx+xml' 的 item
    ncx_href = None
    for item_id, href in _opf_items(opf):
        # 找 item 标签中含 ncx media-type
        item_match = re.search(
            r'<item[^>]+id=["\']' + re.escape(item_id) + r'["\'][^>]*media-type=["\']' + re.escape(_NCX_MEDIA) + r'["\']',
            opf, re.I,
        )
        if item_match:
            ncx_href = href
            break
        # 反过来, href 在前
        item_match = re.search(
            r'<item[^>]+media-type=["\']' + re.escape(_NCX_MEDIA) + r'["\'][^>]+id=["\']' + re.escape(item_id) + r'["\']',
            opf, re.I,
        )
        if item_match:
            ncx_href = href
            break
    # 也看 spine 的 toc 属性 (EPUB 2 通常显式声明)
    if not ncx_href:
        spine_toc = re.search(r'<spine[^>]+toc=["\']([^"\']+)["\']', opf, re.I)
        if spine_toc:
            toc_id = spine_toc.group(1)
            for item_id, href in _opf_items(opf):
                if item_id == toc_id:
                    ncx_href = href
                    break

    if ncx_href:
        ncx_arcname = opf_dir + ncx_href
        try:
            ncx = zf.read(ncx_arcname).decode('utf-8', errors='ignore')
        except KeyError:
            ncx = ''
        if ncx:
            # 找 navMap 块, 逐个 navPoint
            navmap = re.search(r'<navMap[^>]*>(.*?)</navMap>', ncx, re.S | re.I)
            if navmap:
                entries = []
                for np_match in re.finditer(r'<navPoint\b.*?</navPoint>', navmap.group(1), re.S | re.I):
                    block = np_match.group(0)
                    label_m = _NCX_NAVLABEL_TEXT.search(block)
                    src_m = _NCX_CONTENT_SRC.search(block)
                    if label_m and src_m:
                        entries.append({
                            'title': re.sub(r'\s+', ' ',
                                            html.unescape(label_m.group(1))).strip(),
                            'href': src_m.group(1).split('#')[0],  # 去掉 #anchor
                            'level': 0,  # 简化: 不算嵌套
                            'base': ncx_arcname.rsplit('/', 1)[0] + '/' if '/' in ncx_arcname else '',
                        })
                if entries:
                    return entries

    # 2) EPUB 3 nav: 在 content.opf 同目录找 nav.xhtml / toc.xhtml 等
    for candidate in ('nav.xhtml', 'toc.xhtml', 'nav.html'):
        try:
            nav = zf.read(opf_dir + candidate).decode('utf-8', errors='ignore')
        except KeyError:
            continue
        if _NAV_EPUB_TYPE.search(nav):
            entries = []
            for href, title in _NAV_LI.findall(nav):
                t = re.sub(r'\s+', ' ', html.unescape(title)).strip()
                if t:
                    entries.append({
                        'title': t, 'href': href.split('#')[0], 'level': 0,
                        'base': opf_dir,
                    })
            if entries:
                return entries
    return []


def _parse_toc_base(ent: dict) -> str:
    """TOC 条目里 href 相对于哪个目录 —— 由 _parse_toc 写入 base 字段。"""
    return (ent or {}).get('base') or ''


def _resolve_zip_name(zf, href: str, opf_path: str = '', extra_base: str = '') -> str:
    """把 TOC / nav 里的 href 解析成 zip 内真实存在的路径名。

    href 的基准目录在不同 EPUB 里不统一:可能是 OPF 所在目录、NCX 所在目录,
    也可能直接就是 zip 根。这里把常见基准挨个试一遍,谁存在用谁。
    """
    if not href:
        return ''
    href = href.split('#')[0].strip()
    if not href:
        return ''
    names = set(zf.namelist())
    candidates = [href]
    for base in (extra_base, opf_path.rsplit('/', 1)[0] + '/' if '/' in opf_path else ''):
        if not base:
            continue
        joined = (base.rstrip('/') + '/' + href).lstrip('/')
        if joined not in candidates:
            candidates.append(joined)
    for c in candidates:
        if c in names:
            return c
    # 都命中不了时,做一次尾部匹配兜底(有些包 href 带了多余的 ../)
    for c in candidates:
        tail = c.split('/')[-1]
        for n in names:
            if n.split('/')[-1] == tail:
                return n
    return ''


def calc_lexile(book_data):
    title = book_data.get('book', '').lower()

    # 已知蓝思值的书籍 (更精确的值)
    known_books = {
        # Harry Potter 系列
        'philosopher': 880,
        'chamber of secrets': 870,
        'prisoner of azkaban': 870,
        'goblet of fire': 880,
        'order of the phoenix': 900,
        'half-blood prince': 680,
        'deathly hallows': 900,
        # Percy Jackson 系列
        'lightning thief': 590,
        'sea of monsters': 600,
        'titans curse': 620,
        'battle of the labyrinth': 630,
        'last olympian': 620,
        'house of hades': 650,
        'blood of olympus': 650,
        # Diary of a Wimpy Kid
        'diary of a wimpy kid': 800,
        'wimpy kid': 800,
        # Magic Tree House
        'magic tree house': 450,
        'christmas in camelot': 500,
        # 其他
        'treasury of greek': 750,
        'gods goddesses': 750,
        'percy jackson': 600,
    }

    title_normalized = title.replace('_', ' ')
    for key, lexile in known_books.items():
        if key in title_normalized:
            return lexile

    # 通用估算:计算句子平均长度
    total_words = 0
    total_sentences = 0
    for ch in book_data.get('chapters', []):
        for sent in ch.get('sentences', []):
            words = [w for w in sent.split() if re.sub(r'[^a-zA-Z]', '', w)]
            if words:
                total_words += len(words)
                total_sentences += 1

    if total_sentences == 0:
        return 500  # 默认

    avg_sentence_length = total_words / total_sentences

    # 根据句子长度估算 (经验公式)
    if avg_sentence_length < 8:
        return 400
    elif avg_sentence_length < 12:
        return 550
    elif avg_sentence_length < 16:
        return 700
    elif avg_sentence_length < 20:
        return 850
    else:
        return 1000


# 阅读密度:每屏放几句。
# 密度不该由「孩子的水平」单独决定 —— 同一本 500 蓝思的书,700 的孩子该看到
# 一整页,400 的孩子该逐句啃。真正决定密度的是书与孩子的**差值** gap。
# gap 为负 = 书比孩子简单,孩子读得轻松,就该少打断、多给内容;
# gap 为正 = 书比孩子难,必须拆细、留白,否则一页字看着就发怵。
#
# 这是全项目的唯一权威表。web/js/index.js 里的 JS 版必须和它逐档一致,
# tests/test_reading_density.py 里有 parity 测试钉死,防止两边悄悄漂移。
READING_DENSITY_STEPS = (
    # (gap 上界含号, 每屏句数, 模式)
    (-200, 10, 'book'),
    (-50, 7, 'book'),
    (50, 5, 'focus'),
    (150, 4, 'focus'),
    (None, 3, 'focus'),   # gap > 150,书明显比孩子难
)

# 没建档案 / 没填蓝思值时的兜底:按「刚够读」处理,密度居中偏保守。
DEFAULT_CHILD_LEXILE = 600


def calc_reading_density(book_lexile, child_lexile) -> dict:
    """按「书的难度 - 孩子的水平」算出每屏句数与阅读模式。

    返回 {sentencesPerPage, mode, bookLexile, childLexile, gap}。
    mode='focus' 是一屏几句的大字号聚焦(初级);
    mode='book'  是连续小字的书页(高段位),CSS 靠这个 class 切换。

    任何一侧缺失都退回 DEFAULT_CHILD_LEXILE / 500,不抛异常 ——
    阅读器打不开一本书的代价比密度算错大得多。
    """
    try:
        book_l = int(book_lexile) if book_lexile is not None else 500
    except (TypeError, ValueError):
        book_l = 500
    try:
        child_l = int(child_lexile) if child_lexile is not None else DEFAULT_CHILD_LEXILE
    except (TypeError, ValueError):
        child_l = DEFAULT_CHILD_LEXILE
    # 蓝思值有物理上限,填个 9999 不该让 gap 溢出成天文数字
    child_l = max(0, min(child_l, 2000))

    gap = book_l - child_l
    for upper, per_page, mode in READING_DENSITY_STEPS:
        if upper is None or gap <= upper:
            return {
                'sentencesPerPage': per_page,
                'mode': mode,
                'bookLexile': book_l,
                'childLexile': child_l,
                'gap': gap,
            }
    # 循环里必然返回,这里只是让类型检查器闭嘴
    return {'sentencesPerPage': 3, 'mode': 'focus',
            'bookLexile': book_l, 'childLexile': child_l, 'gap': gap}


# === R11: list_books 缓存 ===
# 每次家长打开 parent 页都触发, 旧逻辑要把每本书全 JSON parse + 算 lexile,
# harry_potter 6.7MB + treasury 173KB 等加起来近 10MB 扫描。
# 加个进程内缓存, import/delete 时失效。
_BOOKS_LIST_CACHE = {'data': None, 'ts': 0.0}
_BOOKS_LIST_CACHE_TTL = 30  # 秒, 兜底防 cache 不失效 (e.g. 直接 SQL 改库)


def _invalidate_books_list_cache():
    _BOOKS_LIST_CACHE['data'] = None
    _BOOKS_LIST_CACHE['ts'] = 0.0


def register_routes(app):
    @app.route('/api/book/<book_id>')
    def get_book(book_id):
        """获取书籍内容 (R9: 顶层多返 toc, 旧书无 toc 字段时为 [])"""
        if not is_valid_book_id(book_id):
            return jsonify({"success": False, "error": "非法书籍ID"}), 400
        conn = get_db()
        row = conn.execute('SELECT data_json FROM books WHERE id = ?', (book_id,)).fetchone()
        if not row:
            return jsonify({"success": False, "error": "书籍不存在"}), 404
        book = json.loads(row['data_json'])
        book['id'] = book_id  # 防御性:确保 id 字段存在
        if 'toc' not in book:
            book['toc'] = []
        # 兼容前端: 顶层多返一个 title 字段 (数据存的是 'book' 键, 但前端部分代码读 .title)
        if 'title' not in book or not book['title']:
            book['title'] = book.get('book', book_id)
        if 'cover' in book:
            book['cover'] = _cover_url(book['cover'])
        # 阅读密度要按「书的难度 - 孩子的水平」算,前端拿不到书的蓝思值就没法算。
        book['lexile'] = calc_lexile(book)
        return jsonify({"success": True, "book": book})

    @app.route('/api/child/profile')
    def child_profile():
        """孩子的阅读档案 —— 阅读器要靠它算每屏句数,所以不能要家长鉴权。

        只回算密度必需的三个字段。stats / vocabulary / lookedWords 这些
        仍然锁在 /api/parent/data 后面,不能因为要个蓝思值就把整张表放开。
        档案本身存在 parent_data.settings.child,由家长页写入。
        """
        from extensions.parent_data import load_child_profile
        profile = load_child_profile()
        return jsonify({
            "success": True,
            "child": profile,
            "defaultLexile": DEFAULT_CHILD_LEXILE,
        })

    @app.route('/api/books')
    def list_books():
        """列出所有已导入的书籍 (R9: 多返 author/year/publisher 让书列表显示作者)
        (R11: 加内存缓存, import/delete 时失效)"""
        now = time.time()
        cached = _BOOKS_LIST_CACHE['data']
        if cached is not None and (now - _BOOKS_LIST_CACHE['ts']) < _BOOKS_LIST_CACHE_TTL:
            return jsonify({"success": True, "books": cached})

        conn = get_db()
        books = []
        for row in conn.execute('SELECT id, data_json FROM books ORDER BY updated_at DESC').fetchall():
            book_id, data_json = row['id'], row['data_json']
            data = json.loads(data_json)
            chapters = data.get('chapters', [])
            chapter_sentences = [len(ch.get('sentences', []) or []) for ch in chapters]
            total_sentences = sum(chapter_sentences)
            books.append({
                "id": book_id,
                "title": data.get('book', data.get('title', book_id)),
                "author": data.get('creator'),         # R9: 旧书无该字段 → None
                "year": data.get('year'),
                "publisher": data.get('publisher'),
                "chapters": len(chapters),
                "sentences": total_sentences,
                # 书架页的进度条要知道「读到全书第几句」,光有总数算不出来。
                # 章数少(几十)体积可忽略,换来的是进度条不说谎。
                "chapter_sentences": chapter_sentences,
                "lexile": calc_lexile(data),
                "cover": _cover_url(data.get('cover')),  # R11: 兼容旧绝对路径
            })
        _BOOKS_LIST_CACHE['data'] = books
        _BOOKS_LIST_CACHE['ts'] = now
        return jsonify({"success": True, "books": books})

    @app.route('/api/debug/book/<book_id>/audit')
    def audit_book(book_id):
        """审计书籍解析质量 (R9 fixup 后, 用来发现历史 import 残留问题)。

        扫四类可疑: 短句 (<10字符) / CSS 残留 / 页码候选 (3+连续数字) / 重复内容 (页眉页脚特征)。

        默认 404: 开了 SHADOW_DEBUG=1 才放行,且要家长鉴权。
        原设计是"不需鉴权 + 30/min 限流",但 LAN 上任何设备都能拉到
        全部书籍的解析统计,生产暴露没必要。
        做成请求时判断而不是 import 时不注册路由,是为了让测试能直接打。
        """
        if not _debug_enabled():
            abort(404)
        if not session.get('parent_auth'):
            return jsonify({"success": False, "error": "未授权"}), 401

        if not is_valid_book_id(book_id):
            return jsonify({"success": False, "error": "非法书籍ID"}), 400

        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'tts')
        if not ok:
            return jsonify({
                "success": False,
                "error": f"请求过快, {retry} 秒后再试",
                "retryable": True,
                "retry_after": retry,
            }), 429

        conn = get_db()
        row = conn.execute('SELECT data_json FROM books WHERE id = ?', (book_id,)).fetchone()
        if not row:
            return jsonify({"success": False, "error": "书籍不存在"}), 404

        book = json.loads(row['data_json'])
        chapters = book.get('chapters', [])
        issues_by_chapter = []
        total_sentences = 0
        total_chars = 0

        for idx, ch in enumerate(chapters):
            audit = _audit_chapter(ch)
            audit['chapter'] = idx + 1
            issues_by_chapter.append(audit)
            total_sentences += audit['sentence_count']
            for s in (ch.get('sentences') or []):
                if isinstance(s, str):
                    total_chars += len(s)

        total_issues = sum(
            i['short_sentence_count'] + i['css_residue_count'] +
            i['pagenum_candidate_count'] + i['repeated_count']
            for i in issues_by_chapter
        )

        return jsonify({
            "success": True,
            "book_id": book_id,
            "title": book.get('book', book.get('title', book_id)),
            "total_chapters": len(chapters),
            "total_sentences": total_sentences,
            "avg_sentence_length": round(total_chars / total_sentences, 1) if total_sentences else 0,
            "total_issue_count": total_issues,
            "issues_by_chapter": issues_by_chapter,
        })

    @app.route('/api/book/<book_id>', methods=['DELETE'])
    @require_parent_auth
    def delete_book(book_id):
        """删除书籍 (需家长鉴权)"""
        if not is_valid_book_id(book_id):
            return jsonify({"success": False, "error": "非法书籍ID"}), 400
        conn = get_db()
        # 先取标题再删 —— 删完就查不到了,日志里只剩一个 id 等于没记。
        # 本项目 2026-09-30 出现过 books 表被清空且无任何痕迹的悬案,
        # 就是因为这条路径当时不落日志。
        row = conn.execute('SELECT data_json FROM books WHERE id = ?', (book_id,)).fetchone()
        if row is None:
            return jsonify({"success": False, "error": "书籍不存在"}), 404
        try:
            title = (json.loads(row[0]) or {}).get('book', '?')
        except Exception:
            title = '?(data_json 解析失败)'
        cur = conn.execute('DELETE FROM books WHERE id = ?', (book_id,))
        remaining = conn.execute('SELECT COUNT(*) FROM books').fetchone()[0]
        # 封面文件名由标题推导(_save_cover),不同书必落在不同文件上,
        # 删书不删图只会让 covers/ 越攒越多 —— data/covers/ 里已经躺着
        # 9 个无主封面(bleak_house / harry_potter_1 / percy_jackson_2 ...)。
        # 找不到或标题不可用时静默跳过,删书本身不该因为清理失败而失败。
        try:
            stem = _sanitize_book_id(title)
            if stem:
                for f in COVERS_DIR.glob(f'{stem}.*'):
                    f.unlink()
                    logger.info(f'删除书籍封面: {f.name}')
        except OSError as e:
            logger.warning(f'清理封面失败 book_id={book_id!r}: {e}')
        logger.warning(
            '删除书籍 id=%r title=%r by=%s 剩余=%d',
            book_id, title, request.remote_addr, remaining,
        )
        _invalidate_books_list_cache()
        return jsonify({"success": True, "remaining": remaining})

    @app.route('/api/book/import', methods=['POST'])
    @require_parent_auth
    def import_book():
        """导入 EPUB 电子书 (需家长鉴权)"""
        # Phase 2: import 限流 (10/h/IP)
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'import')
        if not ok:
            return jsonify({"success": False, "error": f"导入过于频繁, {retry} 秒后再试"}), 429

        if 'epub' not in request.files:
            return jsonify({"success": False, "error": "没有上传文件"})

        file = request.files['epub']
        if file.filename == '':
            return jsonify({"success": False, "error": "文件名为空"})

        filename = secure_filename(file.filename)
        if not filename.endswith('.epub'):
            return jsonify({"success": False, "error": "只支持 EPUB 格式"})

        try:
            epub_data = io.BytesIO(file.read())
            # .epub 后缀剥除 (用切片避免 'foo.epub.backup' 被误处理)
            book_title = filename[:-5] if filename.endswith('.epub') else filename
            chapters = []
            cover_path = None

            with zipfile.ZipFile(epub_data, 'r') as zf:
                # === EPUB 合法性校验: 必须是真 EPUB (有 META-INF/container.xml) ===
                opf_path = _find_content_opf_path(zf)
                if not opf_path:
                    return jsonify({"success": False, "error": "不是有效的 EPUB 文件 (缺 META-INF/container.xml)"})

                # === R9: 解析 OPF metadata (title/author/publisher/date/...) + 真 TOC ===
                opf_meta = _parse_opf_metadata(zf, opf_path)
                toc_entries = _parse_toc(zf, opf_path)
                # title 用 OPF 的 (e.g. "Harry Potter and the Philosopher's Stone"), fallback 到 filename
                if opf_meta.get('title'):
                    book_title = opf_meta['title']
                if toc_entries:
                    logger.info(f'解析真 TOC: {len(toc_entries)} 章节')
                else:
                    logger.info('未找到真 TOC, 降级到正则猜章节')

                # === R10: 判重必须在任何写盘动作之前 ===
                # 历史 bug: 判重放在解析末尾,而封面早在 _save_cover 就落盘了。
                # 同 id 再导一次 → 数据确实被 409 拦下没覆盖,但旧书的封面文件
                # 已经被新 EPUB 的封面盖掉,旧书从此顶着新书的封面显示。
                # 判重只依赖 book_title,此处 title 已定稿(OPF 优先),可以提前。
                book_id = _sanitize_book_id(book_title)
                if get_db().execute('SELECT 1 FROM books WHERE id = ?', (book_id,)).fetchone():
                    logger.warning(f'book_id {book_id!r} 已存在, 拒绝覆盖 (filename={filename!r})')
                    return jsonify({
                        "success": False,
                        "error": f'书籍 ID {book_id!r} 已存在, 请重命名文件后重试 (例: {book_id}_v2.epub)',
                        "retryable": False,
                        "book_id": book_id,
                    }), 409

                html_files = [n for n in zf.namelist() if n.endswith(('.html', '.xhtml', '.htm')) and 'image' not in n.lower()]

                # 提取封面: 先走 OPF spec 找, 找不到再按常见文件名猜
                # 1) OPF 路径 (EPUB 2/3 通用, 准确率 ~99%)
                opf_cover_arcname = _find_cover_via_opf(zf, opf_path)
                if opf_cover_arcname:
                    cover_path = _save_cover(zf, book_title, opf_cover_arcname)
                # 2) 常见文件名 fallback (老 EPUB 经常没 meta cover)
                if not cover_path:
                    for pattern in ('cover.jpeg', 'cover.jpg', 'cover.png',
                                    'cover1.jpeg', 'cover1.jpg',
                                    'images/cover.jpg', 'images/cover.jpeg',
                                    'OEBPS/images/cover.jpg'):
                        path = _save_cover(zf, book_title, pattern)
                        if path:
                            cover_path = path
                            break
                if not cover_path:
                    logger.info('未找到封面 (OPF meta 和常见文件名都没命中)')

                # spine 顺序 (走 spec, 不再硬编码 OEBPS/content.opf)
                spine_items = _parse_spine_order(zf, opf_path)
                if not spine_items:
                    logger.warning('解析 spine 失败, 降级到 sorted(html_files)')

                ordered_files = spine_items if spine_items else sorted(html_files)
                current_chapter = None
                current_sentences = []

                # === 章节切分(2026-09-30 重写) ===
                # 历史 bug:断章只靠「这个文件的纯文本短得像标题」,而 _clean_text
                # 返回的是整个文件的全文 —— 几百词,永远不满足 _is_chapter_heading 的
                # ≤8 词 / ≤80 字符,于是 if 分支一次都不走,所有章节内容全堆进第 1 章。
                # 实测 magic tree house 29 这本 24 章的真书被压成 1 章 846 句。
                #
                # 正确做法:有真 TOC 时,一个 TOC 条目 = 一章,标题直接用 TOC 的。
                # 只有拿不到 TOC 的书才退回原来的正则猜法(再不行走每 50 句一章)。
                if toc_entries:
                    seen_arc = set()
                    for ent in toc_entries:
                        href = (ent.get('href') or '').split('#')[0].strip()
                        if not href:
                            continue
                        arc = _resolve_zip_name(zf, href, opf_path, _parse_toc_base(ent))
                        if not arc or arc in seen_arc:
                            continue
                        seen_arc.add(arc)
                        try:
                            content = zf.read(arc).decode('utf-8', errors='ignore')
                        except KeyError:
                            logger.warning(f'TOC 指向的文件不存在: {arc}')
                            continue
                        except Exception as e:
                            logger.warning(f'读 TOC 章节 {arc} 失败: {e}')
                            continue
                        text = _clean_text(content)
                        if not text:
                            continue
                        sents = _split_sentences(text)
                        if sents:
                            chapters.append({
                                "name": ent.get('title') or f'Chapter {len(chapters)+1}',
                                "sentences": sents,
                            })
                    logger.info(f'按 TOC 切出 {len(chapters)} 章 (原 {len(toc_entries)} 条)')
                else:
                    for html_file in ordered_files:
                        if not html_file:
                            continue
                        try:
                            content = zf.read(html_file).decode('utf-8', errors='ignore')
                            text = _clean_text(content)
                            if not text or len(text) < 20:
                                continue

                            # R11: 只用 h1-h6 提取章节标题。
                            # 旧 fallback 用 <title> 是 bug — <title> 是整本书名,
                            # 没 h1-h6 的章节会全部拿到同一个书名作标题。
                            heading_match = re.search(r'<h[1-6][^>]*>([^<]+)</h[1-6]>', content, re.I)
                            chapter_title = heading_match.group(1) if heading_match else ''

                            if _is_chapter_heading(text) and len(text.split()) < 10:
                                if current_chapter and current_sentences:
                                    chapters.append({"name": current_chapter, "sentences": current_sentences})
                                current_chapter = text if text else (chapter_title or f'Chapter {len(chapters)+1}')
                                current_sentences = []
                            else:
                                sents = _split_sentences(text)
                                if sents:
                                    if not current_chapter:
                                        current_chapter = chapter_title or book_title
                                    current_sentences.extend(sents)
                        except Exception as e:
                            logger.warning(f'解析 EPUB 章节 {html_file} 失败: {e}')
                            continue

                if current_chapter and current_sentences:
                    chapters.append({"name": current_chapter, "sentences": current_sentences})

                # Fallback: 每 50 句一章
                if len(chapters) == 0 or all(len(ch.get('sentences', [])) == 0 for ch in chapters):
                    chapters = []
                    current_sentences = []
                    FALLBACK_FILE_CAP = 20
                    if len(ordered_files) > FALLBACK_FILE_CAP:
                        # 以前这里直接 ordered_files[:20],被截掉的章节无声消失,
                        # 家长导入一本 30 章的书只拿到前 20 章且毫无提示。
                        logger.warning(
                            '走 fallback 分章,但 EPUB 有 %d 个章节文件,只处理前 %d 个,'
                            '其余 %d 个被丢弃 —— 本书导入结果不完整',
                            len(ordered_files), FALLBACK_FILE_CAP,
                            len(ordered_files) - FALLBACK_FILE_CAP,
                        )
                    for html_file in ordered_files[:FALLBACK_FILE_CAP]:
                        if not html_file:
                            continue
                        try:
                            content = zf.read(html_file).decode('utf-8', errors='ignore')
                            text = _clean_text(content)
                            sents = _split_sentences(text)
                            current_sentences.extend(sents)
                            if len(current_sentences) >= 50:
                                chapters.append({"name": f"Part {len(chapters)+1}", "sentences": current_sentences[:50]})
                                current_sentences = current_sentences[50:]
                        except Exception as e:
                            logger.warning(f'解析HTML章节失败: {e}')
                            continue
                    if current_sentences:
                        chapters.append({"name": f"Part {len(chapters)+1}", "sentences": current_sentences})

                # 合并太短章节 + 过滤空
                merged_chapters = [ch for ch in chapters if ch.get('sentences') and len(ch['sentences']) >= 3]
                total_sentences = sum(len(ch['sentences']) for ch in merged_chapters)

            # === Phase 3a: 写入 SQLite (不再写 JSON) ===
            book_id = _sanitize_book_id(book_title)
            book_data = {
                "book": book_title,
                "id": book_id,
                "chapters": merged_chapters,
                "cover": cover_path,
                # R9: 顶层 OPF metadata 字段 (老 book 导入时无这些字段 → API 端用 .get 返 None)
                "creator": opf_meta.get('creator'),
                "publisher": opf_meta.get('publisher'),
                "date": opf_meta.get('date'),
                "year": opf_meta.get('year'),
                "language": opf_meta.get('language'),
                "description": opf_meta.get('description'),
                "identifier": opf_meta.get('identifier'),
                "subjects": opf_meta.get('subjects') or [],
                "rights": opf_meta.get('rights'),
                "toc": toc_entries,  # 真 TOC, 无则 []
            }
            conn = get_db()
            now = int(time.time() * 1000)
            conn.execute(
                'INSERT OR REPLACE INTO books (id, data_json, imported_at, updated_at) '
                'VALUES (?, ?, ?, ?)',
                (book_id, json.dumps(book_data, ensure_ascii=False), now, now)
            )
            _invalidate_books_list_cache()
            return jsonify({
                "success": True,
                "book_id": book_id,
                "book_title": book_title,
                "author": opf_meta.get('creator'),
                "total_chapters": len(merged_chapters),
                "total_sentences": total_sentences,
                "has_cover": bool(cover_path),
                "has_toc": bool(toc_entries),
            })

        except Exception as e:
            logger.exception('EPUB 导入失败')
            return jsonify({"success": False, "error": "导入失败: " + type(e).__name__}), 500

    @app.route('/data/covers/<path:filename>')
    def serve_covers(filename):
        """提供封面图片"""
        return send_from_directory(str(COVERS_DIR), filename)