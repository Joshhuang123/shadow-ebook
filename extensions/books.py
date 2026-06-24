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
import re
import html
import time
import zipfile
from pathlib import Path
from flask import jsonify, request, send_from_directory
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
_OPF_ITEM = re.compile(r'<item[^>]+id=["\']([^"\']+)["\'][^>]+href=["\']([^"\']+)["\']')
_OPF_COVER_META = re.compile(r'<meta[^>]+name=["\']cover["\'][^>]+content=["\']([^"\']+)["\']', re.I)
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
    spine_ids = _OPF_ITEMREF.findall(opf)
    id_to_file = dict(_OPF_ITEM.findall(opf))
    # opf_path 可能带子目录 (如 OEBPS/content.opf), href 是相对路径
    opf_dir = opf_path.rsplit('/', 1)[0] + '/' if '/' in opf_path else ''
    return [opf_dir + id_to_file[sid] for sid in spine_ids if sid in id_to_file]


def _find_cover_via_opf(zf, opf_path: str) -> str:
    """走 EPUB spec 找封面: <meta name="cover" content="item_id"> → manifest id → href。
    找不到返回 ''。比文件名猜更准 (尤其对不按 cover.jpg 命名的书)。"""
    if not opf_path:
        return ''
    try:
        opf = zf.read(opf_path).decode('utf-8', errors='ignore')
    except KeyError:
        return ''
    m = _OPF_COVER_META.search(opf)
    if not m:
        return ''
    cover_id = m.group(1)
    # 找 manifest 里 id == cover_id 的 item
    for item_id, href in _OPF_ITEM.findall(opf):
        if item_id == cover_id:
            # href 是相对 opf_dir 的路径
            opf_dir = opf_path.rsplit('/', 1)[0] + '/' if '/' in opf_path else ''
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
    for item_id, href in _OPF_ITEM.findall(opf):
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
            for item_id, href in _OPF_ITEM.findall(opf):
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
                            'title': re.sub(r'\s+', ' ', label_m.group(1)).strip(),
                            'href': src_m.group(1).split('#')[0],  # 去掉 #anchor
                            'level': 0,  # 简化: 不算嵌套
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
                t = re.sub(r'\s+', ' ', title).strip()
                if t:
                    entries.append({'title': t, 'href': href.split('#')[0], 'level': 0})
            if entries:
                return entries
    return []


def calc_lexile(book_data):
    """根据书名估算蓝思值 (因为句子数据不完整)"""
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
        return jsonify({"success": True, "book": book})

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
            total_sentences = sum(len(ch.get('sentences', [])) for ch in chapters)
            books.append({
                "id": book_id,
                "title": data.get('book', data.get('title', book_id)),
                "author": data.get('creator'),         # R9: 旧书无该字段 → None
                "year": data.get('year'),
                "publisher": data.get('publisher'),
                "chapters": len(chapters),
                "sentences": total_sentences,
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
        不需鉴权 (debug 用途), 走 tts bucket 限流 (30/min 够家长偶尔调)。
        """
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
        cur = conn.execute('DELETE FROM books WHERE id = ?', (book_id,))
        if cur.rowcount == 0:
            return jsonify({"success": False, "error": "书籍不存在"}), 404
        _invalidate_books_list_cache()
        return jsonify({"success": True})

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
                    for html_file in ordered_files[:20]:
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
            # === R10: 重复 import 不再静默覆盖, 返 409 引导家长重命名 ===
            # 历史: Round 4 只 log warning, 实际用 INSERT OR REPLACE 静默覆盖老书
            # (用户 import 一本新书如果 title 跟老书算出的 book_id 一样, 老书数据被无提示替换)
            existing = conn.execute('SELECT 1 FROM books WHERE id = ?', (book_id,)).fetchone()
            if existing:
                logger.warning(f'book_id {book_id!r} 已存在, 拒绝覆盖 (filename={filename!r})')
                return jsonify({
                    "success": False,
                    "error": f'书籍 ID {book_id!r} 已存在, 请重命名文件后重试 (例: {book_id}_v2.epub)',
                    "retryable": False,
                    "book_id": book_id,
                }), 409
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
                "has_cover": cover_path is not None,
                "has_toc": bool(toc_entries),
            })

        except Exception as e:
            logger.exception('EPUB 导入失败')
            return jsonify({"success": False, "error": "导入失败: " + type(e).__name__}), 500

    @app.route('/data/covers/<path:filename>')
    def serve_covers(filename):
        """提供封面图片"""
        return send_from_directory(str(COVERS_DIR), filename)