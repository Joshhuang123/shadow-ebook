"""
Owns: book metadata, book import (EPUB parsing), book list cache, book cover serving,
lexile estimation, secure book_id validation (path-traversal defense).
Does NOT own: TTS for book sentences (tts.py), parent stats (parent_data.py), DB layer (db.py).

Phase 3a: books 改走 SQLite (data/shadow.db),原 data/books/*.json 在首次启动时自动迁入,
        备份在 data/books.migrated-<ts>/ 留 30 天。
"""
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
BOOK_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')
COVERS_DIR = Path(__file__).resolve().parent.parent / 'data' / 'covers'


def is_valid_book_id(book_id):
    return bool(book_id and BOOK_ID_PATTERN.match(book_id))


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


def register_routes(app):
    @app.route('/api/book/<book_id>')
    def get_book(book_id):
        """获取书籍内容"""
        if not is_valid_book_id(book_id):
            return jsonify({"success": False, "error": "非法书籍ID"}), 400
        conn = get_db()
        row = conn.execute('SELECT data_json FROM books WHERE id = ?', (book_id,)).fetchone()
        if not row:
            return jsonify({"success": False, "error": "书籍不存在"}), 404
        book = json.loads(row['data_json'])
        book['id'] = book_id  # 防御性:确保 id 字段存在
        return jsonify({"success": True, "book": book})

    @app.route('/api/books')
    def list_books():
        """列出所有已导入的书籍 (Phase 3a: 直查 DB, 无缓存 — WAL 模式下 mtime 不可靠)"""
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
                "chapters": len(chapters),
                "sentences": total_sentences,
                "lexile": calc_lexile(data),
                "cover": data.get('cover')
            })
        return jsonify({"success": True, "books": books})

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
            book_title = filename.replace('.epub', '')
            chapters = []
            cover_path = None

            with zipfile.ZipFile(epub_data, 'r') as zf:
                html_files = [n for n in zf.namelist() if n.endswith(('.html', '.xhtml', '.htm')) and 'image' not in n.lower()]

                # 提取封面
                try:
                    cover_patterns = ['cover.jpeg', 'cover.jpg', 'cover.png', 'cover1.jpeg', 'cover1.jpg',
                                      'images/cover.jpg', 'images/cover.jpeg', 'OEBPS/images/cover.jpg']
                    for pattern in cover_patterns:
                        try:
                            img_data = zf.read(pattern)
                            if len(img_data) > 1000:
                                COVERS_DIR.mkdir(parents=True, exist_ok=True)
                                book_id_for_cover = re.sub(r'[^a-zA-Z0-9_-]', '_', filename.replace('.epub', '').lower())
                                ext = pattern.split('.')[-1].lower()
                                cover_filename = f'{book_id_for_cover}.{ext}'
                                cover_path_full = COVERS_DIR / cover_filename
                                with open(cover_path_full, 'wb') as f:
                                    f.write(img_data)
                                cover_path = f'/data/covers/{cover_filename}'
                                logger.info(f'封面已提取: {cover_filename}')
                                break
                        except Exception as e:
                            logger.warning(f'尝试封面图案失败: {e}')
                            continue
                except Exception as e:
                    logger.warning(f'提取封面出错: {e}')

                # spine 顺序
                spine_items = []
                try:
                    content_opf = zf.read('OEBPS/content.opf').decode('utf-8')
                    spine_ids = re.findall(r'<itemref[^>]+idref=["\']([^"\']+)["\']', content_opf)
                    id_to_file = dict(re.findall(r'<item[^>]+id=["\']([^"\']+)["\'][^>]+href=["\']([^"\']+)["\']', content_opf))
                    spine_items = [id_to_file.get(sid, '') for sid in spine_ids if sid in id_to_file]
                except Exception as e:
                    logger.warning(f'解析spine顺序失败: {e}')

                ordered_files = spine_items if spine_items else sorted(html_files)
                current_chapter = None
                current_sentences = []

                def clean_text(text):
                    text = html.unescape(text)
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = re.sub(r'\s+', ' ', text).strip()
                    return text

                def split_sentences(text):
                    """智能分句,避开称谓缩写 / 国家缩写 / 数字小数点 / 省略号"""
                    PLACEHOLDER = '\x00'
                    text = re.sub(r'\b(Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|Mt|vs|etc)\.', r'\1' + PLACEHOLDER, text)
                    text = re.sub(r'\b([A-Z])\.', r'\1' + PLACEHOLDER, text)
                    text = re.sub(r'(\d)\.(\d)', r'\1' + PLACEHOLDER + r'\2', text)
                    text = text.replace('...', PLACEHOLDER * 3)
                    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z"\'(])', text)
                    sentences = []
                    for p in parts:
                        p = p.strip().replace(PLACEHOLDER, '.').strip('"\' ')
                        if len(p) > 10 and len(p.split()) >= 3:
                            sentences.append(p)
                    return sentences

                def is_chapter_heading(text):
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

                        title_match = re.search(r'<title[^>]*>([^<]+)</title>', content, re.I)
                        heading_match = re.search(r'<h[1-6][^>]*>([^<]+)</h[1-6]>', content, re.I)
                        chapter_title = heading_match.group(1) if heading_match else (title_match.group(1) if title_match else '')

                        if is_chapter_heading(text) and len(text.split()) < 10:
                            if current_chapter and current_sentences:
                                chapters.append({"name": current_chapter, "sentences": current_sentences})
                            current_chapter = text if text else (chapter_title or f'Chapter {len(chapters)+1}')
                            current_sentences = []
                        else:
                            sents = split_sentences(text)
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

                # 合并太短章节 + 过滤空
                merged_chapters = [ch for ch in chapters if ch.get('sentences') and len(ch['sentences']) >= 3]
                total_sentences = sum(len(ch['sentences']) for ch in merged_chapters)

            # === Phase 3a: 写入 SQLite (不再写 JSON) ===
            book_id = re.sub(r'[^a-zA-Z0-9_-]', '_', filename.replace('.epub', '').lower())
            book_data = {
                "book": book_title,
                "id": book_id,
                "chapters": merged_chapters,
                "cover": cover_path,
            }
            conn = get_db()
            now = int(time.time() * 1000)
            conn.execute(
                'INSERT OR REPLACE INTO books (id, data_json, imported_at, updated_at) '
                'VALUES (?, ?, ?, ?)',
                (book_id, json.dumps(book_data, ensure_ascii=False), now, now)
            )
            return jsonify({
                "success": True,
                "book_id": book_id,
                "book_title": book_title,
                "total_chapters": len(merged_chapters),
                "total_sentences": total_sentences,
                "has_cover": cover_path is not None
            })

        except Exception as e:
            logger.exception('EPUB 导入失败')
            return jsonify({"success": False, "error": "导入失败: " + type(e).__name__})

    @app.route('/data/covers/<path:filename>')
    def serve_covers(filename):
        """提供封面图片"""
        return send_from_directory(str(COVERS_DIR), filename)