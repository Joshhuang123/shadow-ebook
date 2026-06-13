"""
Owns: book metadata, book import (EPUB parsing), book list cache, book cover serving,
lexile estimation, secure book_id validation (path-traversal defense).
Does NOT own: TTS for book sentences (tts.py), parent stats (parent_data.py).
"""
import io
import json
import logging
import os
import re
import html
import threading
import zipfile
import traceback
from pathlib import Path
from flask import jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from extensions.auth import require_parent_auth, _api_rate_limit_ok
from extensions.db import _safe_write_json


logger = logging.getLogger(__name__)


# === 路径穿越防御: book_id 只能含字母数字下划线连字符 ===
BOOK_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')
BOOKS_DIR = (Path(__file__).resolve().parent.parent / 'data' / 'books').resolve()
COVERS_DIR = Path(__file__).resolve().parent.parent / 'data' / 'covers'


def is_valid_book_id(book_id):
    return bool(book_id and BOOK_ID_PATTERN.match(book_id))


def safe_book_path(book_id):
    """返回 book 的绝对路径, 失败返回 None (防止路径穿越 + symlink 攻击)"""
    if not is_valid_book_id(book_id):
        return None
    p = (BOOKS_DIR / f'{book_id}.json').resolve()
    # 必须在 BOOKS_DIR 之下
    if not str(p).startswith(str(BOOKS_DIR) + os.sep):
        return None
    return p


# === list_books 缓存: mtime-based, books 目录或任一 book JSON 变更时自动失效 ===
_BOOKS_CACHE = {"key": None, "result": None}
_BOOKS_CACHE_LOCK = threading.Lock()  # Phase 2 加锁


def _books_cache_key(books_dir: Path):
    """基于目录 mtime + 各文件 mtime 的缓存 key"""
    try:
        dir_mtime = books_dir.stat().st_mtime
    except FileNotFoundError:
        return None
    file_mtimes = tuple(sorted(
        (f.stat().st_mtime, f.name) for f in books_dir.glob('*.json')
    ))
    return (dir_mtime, file_mtimes)


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

    # 查找匹配 (统一将下划线转为空格进行匹配)
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
    # 10词左右 ~500L, 15词 ~700L, 20词 ~850L, 25词~1000L
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


def register_routes(app):
    @app.route('/api/book/<book_id>')
    def get_book(book_id):
        """获取书籍内容"""
        book_path = safe_book_path(book_id)
        if book_path is None:
            return jsonify({"success": False, "error": "非法书籍ID"}), 400
        if not book_path.exists():
            return jsonify({"success": False, "error": "书籍不存在"}), 404
        return jsonify({"success": True, "book": json.loads(book_path.read_text())})

    @app.route('/api/books')
    def list_books():
        """列出所有已导入的书籍 (有 mtime 缓存)"""
        with _BOOKS_CACHE_LOCK:
            books_dir = BOOKS_DIR
            books_dir.mkdir(parents=True, exist_ok=True)

            # 缓存命中:目录和文件 mtime 没变就复用
            key = _books_cache_key(books_dir)
            if key is not None and key == _BOOKS_CACHE["key"]:
                return jsonify({"success": True, "books": _BOOKS_CACHE["result"]})

            books = []
            for f in books_dir.glob('*.json'):
                try:
                    data = json.loads(f.read_text())
                    total_sentences = sum(len(ch.get('sentences', [])) for ch in data.get('chapters', []))
                    lexile = calc_lexile(data)
                    books.append({
                        "id": f.stem,
                        "title": data.get('book', data.get('title', f.stem)),
                        "chapters": len(data.get('chapters', [])),
                        "sentences": total_sentences,
                        "lexile": lexile,
                        "cover": data.get('cover')
                    })
                except Exception as e:
                    logger.warning(f"加载书籍失败 {f.stem}: {e}")

            # 写入缓存
            if key is not None:
                _BOOKS_CACHE["key"] = key
                _BOOKS_CACHE["result"] = books

            return jsonify({"success": True, "books": books})

    @app.route('/api/book/<book_id>', methods=['DELETE'])
    @require_parent_auth
    def delete_book(book_id):
        """删除书籍 (需家长鉴权)"""
        book_path = safe_book_path(book_id)
        if book_path is None:
            return jsonify({"success": False, "error": "非法书籍ID"}), 400
        if not book_path.exists():
            return jsonify({"success": False, "error": "书籍不存在"}), 404
        book_path.unlink()
        return jsonify({"success": True})

    @app.route('/api/book/import', methods=['POST'])
    @require_parent_auth
    def import_book():
        """导入 EPUB 电子书 (需家长鉴权)"""
        # Phase 2 新增: import 限流 (10/h/IP),防 100MB 上传被滥用
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
            # 读取 EPUB (zip 格式)
            epub_data = io.BytesIO(file.read())

            book_title = filename.replace('.epub', '')
            chapters = []
            cover_path = None

            with zipfile.ZipFile(epub_data, 'r') as zf:
                # 找所有 HTML/XHTML 文件
                html_files = [n for n in zf.namelist() if n.endswith(('.html', '.xhtml', '.htm')) and 'image' not in n.lower()]

                # 提取封面图片 - 直接查找常见的封面文件名
                try:
                    cover_patterns = ['cover.jpeg', 'cover.jpg', 'cover.png', 'cover1.jpeg', 'cover1.jpg',
                                      'images/cover.jpg', 'images/cover.jpeg', 'OEBPS/images/cover.jpg']
                    for pattern in cover_patterns:
                        try:
                            img_data = zf.read(pattern)
                            if len(img_data) > 1000:  # 确保是真实的图片
                                COVERS_DIR.mkdir(parents=True, exist_ok=True)
                                book_id_for_cover = re.sub(r'[^a-zA-Z0-9_-]', '_', filename.replace('.epub', '').lower())
                                ext = pattern.split('.')[-1].lower()
                                cover_filename = f'{book_id_for_cover}.{ext}'
                                cover_path = COVERS_DIR / cover_filename
                                with open(cover_path, 'wb') as f:
                                    f.write(img_data)
                                cover_path = f'/data/covers/{cover_filename}'
                                logger.info(f'封面已提取: {cover_filename}')
                                break
                        except Exception as e:
                            logger.warning(f'尝试封面图案失败: {e}')
                            continue
                except Exception as e:
                    logger.warning(f'提取封面出错: {e}')

                # 尝试从 content.opf 读取 spine 顺序
                spine_items = []
                try:
                    # 重新读取 content.opf (因为上面的代码可能修改了变量)
                    content_opf = zf.read('OEBPS/content.opf').decode('utf-8')
                    # 提取 spine 中的 idref
                    spine_ids = re.findall(r'<itemref[^>]+idref=["\']([^"\']+)["\']', content_opf)
                    # 提取 id 到文件名映射
                    id_to_file = dict(re.findall(r'<item[^>]+id=["\']([^"\']+)["\'][^>]+href=["\']([^"\']+)["\']', content_opf))
                    spine_items = [id_to_file.get(sid, '') for sid in spine_ids if sid in id_to_file]
                except Exception as e:
                    logger.warning(f'解析spine顺序失败: {e}')

                # 按 spine 顺序处理文件, 没有 spine 则按文件名排序
                ordered_files = spine_items if spine_items else sorted(html_files)

                current_chapter = None
                current_sentences = []

                def clean_text(text):
                    """清理 HTML 标签, 提取纯文本"""
                    text = html.unescape(text)
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = re.sub(r'\s+', ' ', text).strip()
                    return text

                def split_sentences(text):
                    """将文本拆分成句子
                    智能分句: 避开称谓缩写 (Mr./Dr./Mrs.) / 国家缩写 (U.S.A.) / 数字小数点 / 省略号

                    Phase 2 修: 原代码用 `_re.sub` (NameError at runtime),改为 `re.sub`。
                    """
                    # 1. 先保护"非句末"的点 - 用占位符替换, 分完句再还原
                    PLACEHOLDER = '\x00'
                    # 称谓: Mr. Dr. Mrs. Ms. Prof. Sr. Jr. St. Mt. vs. etc.
                    text = re.sub(r'\b(Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|Mt|vs|etc)\.', r'\1' + PLACEHOLDER, text)
                    # 单字母缩写序列: U.S.A. / U.K. / U.S.
                    text = re.sub(r'\b([A-Z])\.', r'\1' + PLACEHOLDER, text)
                    # 数字小数点: 1.5  2.0  3.14
                    text = re.sub(r'(\d)\.(\d)', r'\1' + PLACEHOLDER + r'\2', text)
                    # 省略号: ...
                    text = text.replace('...', PLACEHOLDER * 3)

                    # 2. 按真正的句末标点切分 (句末 + 空白 + 大写/引号/左括号 = 新句开始)
                    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z"\'(])', text)

                    # 3. 还原占位符 + 去引号
                    sentences = []
                    for p in parts:
                        p = p.strip().replace(PLACEHOLDER, '.').strip('"\' ')
                        if len(p) > 10 and len(p.split()) >= 3:
                            sentences.append(p)
                    return sentences

                def is_chapter_heading(text):
                    """判断是否是章节标题"""
                    # 全大写或很短且不含小写字母的可能是标题
                    if len(text) < 60 and len(text.split()) < 5:
                        return True
                    return False

                for html_file in ordered_files:
                    if not html_file:
                        continue
                    try:
                        content = zf.read(html_file).decode('utf-8', errors='ignore')
                        text = clean_text(content)

                        if not text or len(text) < 20:
                            continue

                        # 尝试提取标题 (从 <title> 标签或第一个 <h1>-<h6> 标签)
                        title_match = re.search(r'<title[^>]*>([^<]+)</title>', content, re.I)
                        heading_match = re.search(r'<h[1-6][^>]*>([^<]+)</h[1-6]>', content, re.I)
                        chapter_title = heading_match.group(1) if heading_match else (title_match.group(1) if title_match else '')

                        # 如果文本很短且像是标题
                        if is_chapter_heading(text) and len(text.split()) < 10:
                            if current_chapter and current_sentences:
                                # 保存上一章
                                chapters.append({"name": current_chapter, "sentences": current_sentences})
                            current_chapter = text if text else (chapter_title or f'Chapter {len(chapters)+1}')
                            current_sentences = []
                        else:
                            # 作为正文处理
                            sents = split_sentences(text)
                            if sents:
                                if not current_chapter:
                                    current_chapter = chapter_title or book_title
                                current_sentences.extend(sents)

                    except Exception as e:
                        continue

                # 保存最后一章
                if current_chapter and current_sentences:
                    chapters.append({"name": current_chapter, "sentences": current_sentences})

                # 如果没识别出章节, 把每 50 句合成一章
                if len(chapters) == 0 or all(len(ch.get('sentences', [])) == 0 for ch in chapters):
                    chapters = []
                    current_sentences = []
                    for html_file in ordered_files[:20]:  # 最多处理 20 个文件
                        if not html_file:
                            continue
                        try:
                            content = zf.read(html_file).decode('utf-8', errors='ignore')
                            text = clean_text(content)
                            sents = split_sentences(text)
                            current_sentences.extend(sents)
                            if len(current_sentences) >= 50:
                                chapters.append({"name": f"Part {len(chapters)+1}", "sentences": current_sentences[:50]})
                                current_sentences = current_sentences[50:]
                        except Exception as e:
                            logger.warning(f'解析HTML章节失败: {e}')
                            continue
                    if current_sentences:
                        chapters.append({"name": f"Part {len(chapters)+1}", "sentences": current_sentences})

                # 合并太短的章节
                merged_chapters = []
                for ch in chapters:
                    if ch.get('sentences') and len(ch['sentences']) >= 3:
                        merged_chapters.append(ch)

                # 过滤空章节
                merged_chapters = [ch for ch in merged_chapters if ch.get('sentences')]
                total_sentences = sum(len(ch['sentences']) for ch in merged_chapters)

            # 保存到文件
            book_id = re.sub(r'[^a-zA-Z0-9_-]', '_', filename.replace('.epub', '').lower())
            book_path = BOOKS_DIR / f'{book_id}.json'
            book_data = {
                "book": book_title,
                "id": book_id,
                "chapters": merged_chapters,
                "cover": cover_path  # 如果提取到封面会有值
            }
            book_path.parent.mkdir(parents=True, exist_ok=True)
            _safe_write_json(book_path, book_data)

            return jsonify({
                "success": True,
                "book_id": book_id,
                "book_title": book_title,
                "total_chapters": len(merged_chapters),
                "total_sentences": total_sentences,
                "has_cover": cover_path is not None
            })

        except Exception as e:
            traceback.print_exc()
            return jsonify({"success": False, "error": "导入失败: " + type(e).__name__})

    @app.route('/data/covers/<path:filename>')
    def serve_covers(filename):
        """提供封面图片"""
        return send_from_directory(str(COVERS_DIR), filename)