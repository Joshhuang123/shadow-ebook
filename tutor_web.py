#!/usr/bin/env python3
"""
Shadow Learning - 英语跟读辅导系统
显示句子 → TTS朗读 → 孩子跟读 → 评价反馈 → 理解题测试
"""
import os
import re
import sys
import time
import json
import secrets
import hashlib
from pathlib import Path
from functools import wraps
from flask import (
    Flask, render_template, jsonify, request, send_from_directory,
    session, redirect, url_for,
)

app = Flask(__name__, template_folder='web', static_folder='web')
app.config['SECRET_KEY'] = os.environ.get('SHADOW_SECRET', secrets.token_hex(32))
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB 上传上限
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# 路径穿越防御: book_id 只能含字母数字下划线连字符
BOOK_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')
BOOKS_DIR = (Path(__file__).parent / 'data' / 'books').resolve()
PARENT_DATA_DIR = (Path(__file__).parent / 'data' / 'parent').resolve()
PARENT_DATA_DIR.mkdir(parents=True, exist_ok=True)

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

# 家长鉴权 decorator, 必须在使用它的路由之前定义
def require_parent_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('parent_auth'):
            return jsonify({"success": False, "error": "未授权"}), 401
        return f(*args, **kwargs)
    return wrapper

# 登录限流: 防止 LAN 上有人暴力破解 4 位 PIN
# 每个 IP 在 WINDOW_SEC 内最多 MAX_ATTEMPTS 次失败尝试, 之后锁定 LOCKOUT_SEC
_LOGIN_WINDOW = {}  # ip -> [timestamp, ...]
MAX_ATTEMPTS = 5
WINDOW_SEC = 300  # 5 分钟
LOCKOUT_SEC = 900  # 锁定 15 分钟

def _login_rate_limit_ok(ip):
    """返回 (ok, retry_after_sec)"""
    now = time.time()
    arr = _LOGIN_WINDOW.get(ip, [])
    # 清理过期的
    arr = [t for t in arr if now - t < LOCKOUT_SEC]
    if len(arr) >= MAX_ATTEMPTS:
        retry = int(LOCKOUT_SEC - (now - arr[0]))
        return False, max(retry, 1)
    _LOGIN_WINDOW[ip] = arr
    return True, 0

def _login_record_failure(ip):
    arr = _LOGIN_WINDOW.setdefault(ip, [])
    arr.append(time.time())

def _login_clear(ip):
    _LOGIN_WINDOW.pop(ip, None)

def send_html(filename):
    """统一返回 HTML 文件，避免路径拼接问题"""
    return send_from_directory(str(Path(__file__).parent / 'web'), filename)

# ==================== 课程内容 ====================

# 新概念2A 核心句子（按单元组织）
COURSE_CONTENT = {
    "name": "新概念英语青少版2A",
    "units": [
        {
            "name": "Unit 1-2: 现在进行时",
            "sentences": [
                {"text": "What are you doing?", "translation": "你在做什么？", "grammar": "现在进行时 be + doing"},
                {"text": "I'm waiting for you.", "translation": "我在等你。", "grammar": "主语+be+动词ing"},
                {"text": "What is Robert doing?", "translation": "Robert在做什么？", "grammar": "现在进行时疑问句"},
                {"text": "He is reading a book.", "translation": "他在读书。", "grammar": "现在进行时"},
                {"text": "The children are playing in the garden.", "translation": "孩子们正在花园里玩。", "grammar": "现在进行时复数"},
                {"text": "Are you listening to me?", "translation": "你在听我说话吗？", "grammar": "现在进行时一般疑问句"},
                {"text": "Yes, I am. / No, I'm not.", "translation": "是的，我在听。/ 不，我没在听。", "grammar": "肯定/否定回答"},
            ]
        },
        {
            "name": "Unit 5-6: 一般现在时",
            "sentences": [
                {"text": "I usually get up at seven o'clock.", "translation": "我通常七点起床。", "grammar": "一般现在时 习惯性动作"},
                {"text": "When do you usually have breakfast?", "translation": "你通常什么时候吃早饭？", "grammar": "When提问 时间"},
                {"text": "I usually have breakfast at half past seven.", "translation": "我通常七点半吃早饭。", "grammar": "时间表达"},
                {"text": "She often goes to school by bike.", "translation": "她经常骑自行车去学校。", "grammar": "第三人称单数 goes"},
                {"text": "He usually gets up early.", "translation": "他通常早起。", "grammar": "第三人称单数 gets"},
                {"text": "Do you often read English books?", "translation": "你经常读英语书吗？", "grammar": "一般现在时疑问句"},
                {"text": "Yes, I do. / No, I don't.", "translation": "是的，我经常读。/ 不，我不经常读。", "grammar": "简略回答"},
            ]
        },
        {
            "name": "Unit 7: 频率",
            "sentences": [
                {"text": "How often do you go to the cinema?", "translation": "你多久去看一次电影？", "grammar": "频率提问 How often"},
                {"text": "I go to the cinema once a week.", "translation": "我每周去看一次电影。", "grammar": "once a week 频率"},
                {"text": "She exercises twice a day.", "translation": "她每天锻炼两次。", "grammar": "twice频率"},
                {"text": "We usually eat out once a month.", "translation": "我们通常每月出去吃一次饭。", "grammar": "频率 usually+once"},
            ]
        },
        {
            "name": "Unit 8: be going to",
            "sentences": [
                {"text": "What are you going to do this weekend?", "translation": "你这个周末打算做什么？", "grammar": "be going to 表计划"},
                {"text": "I'm going to visit my grandmother.", "translation": "我打算去看望奶奶。", "grammar": "be going to + 动词原形"},
                {"text": "She's going to buy a new dress.", "translation": "她打算买一条新裙子。", "grammar": "be going to 第三人称"},
                {"text": "What are you going to be when you grow up?", "translation": "你长大后想成为什么？", "grammar": "be going to 将来"},
            ]
        },
        {
            "name": "Unit 9: want to do",
            "sentences": [
                {"text": "What do you want to do?", "translation": "你想做什么？", "grammar": "want to do 想要做某事"},
                {"text": "I want to play football.", "translation": "我想踢足球。", "grammar": "want to + 动词原形"},
                {"text": "I want you to help me with my English.", "translation": "我想要你帮我学英语。", "grammar": "want sb to do"},
                {"text": "Do you want to learn English?", "translation": "你想学英语吗？", "grammar": "want to do 疑问句"},
            ]
        },
        {
            "name": "Unit 11: 一般过去时 - be动词",
            "sentences": [
                {"text": "Were you at school yesterday?", "translation": "昨天你在学校吗？", "grammar": "一般过去时 were 疑问"},
                {"text": "Yes, I was. / No, I wasn't.", "translation": "是的，我在。/ 不，我不在。", "grammar": "wasn't = was not"},
                {"text": "She was at home this morning.", "translation": "今天早上她在家里。", "grammar": "was 用于单数"},
                {"text": "They were very happy last night.", "translation": "昨晚他们很开心。", "grammar": "were 用于复数"},
                {"text": "I was ill yesterday.", "translation": "昨天我生病了。", "grammar": "was 过去状态"},
            ]
        },
        {
            "name": "Unit 12-13: 一般过去时 - 动词",
            "sentences": [
                {"text": "I visited my grandmother yesterday.", "translation": "昨天我去看望了奶奶。", "grammar": "规则动词过去式 -ed"},
                {"text": "She played tennis last weekend.", "translation": "上周末她打了网球。", "grammar": "规则动词 played"},
                {"text": "Did you go to school yesterday?", "translation": "昨天你去学校了吗？", "grammar": "Did + 主语 + 动词原形？"},
                {"text": "Yes, I did. / No, I didn't.", "translation": "是的，我去了。/ 不，我没去。", "grammar": "didn't = did not"},
                {"text": "What did you do last weekend?", "translation": "上周末你做了什么？", "grammar": "What did + 主语 + do?"},
            ]
        },
        {
            "name": "Unit 3: 名词性物主代词",
            "sentences": [
                {"text": "Whose is this book?", "translation": "这本书是谁的？", "grammar": "Whose 提问归属"},
                {"text": "It's mine.", "translation": "这是我的。", "grammar": "mine = my book"},
                {"text": "Is this your bag?", "translation": "这是你的包吗？", "grammar": "your 形容词性物主代词"},
                {"text": "No, it's hers.", "translation": "不，这是她的。", "grammar": "hers = her bag"},
                {"text": "These shoes are theirs.", "translation": "这些鞋是他们的。", "grammar": "theirs = their shoes"},
            ]
        },
        {
            "name": "Unit 4: 祈使句",
            "sentences": [
                {"text": "Open the door, please.", "translation": "请开门。", "grammar": "肯定祈使句"},
                {"text": "Don't be late!", "translation": "别迟到！", "grammar": "否定祈使句 Don't + 动词原形"},
                {"text": "Don't take your gloves off.", "translation": "别脱下手套。", "grammar": "否定祈使句"},
                {"text": "Sit down, please.", "translation": "请坐下。", "grammar": "祈使句"},
                {"text": "Listen to me carefully.", "translation": "认真听我说。", "grammar": "祈使句 listen to"},
            ]
        },
    ]
}

# ==================== 理解题题库 ====================

COMPREHENSION_QUESTIONS = {
    "现在进行时": [
        {"question": "What are you doing now?", "options": ["I am reading", "I read", "I will read"], "answer": 0},
        {"question": "Is she playing tennis?", "options": ["Yes, she is", "Yes, she does", "No, she don't"], "answer": 0},
    ],
    "一般现在时": [
        {"question": "He ___ English every day. (like)", "options": ["like", "likes", "liking"], "answer": 1},
        {"question": "When ___ you get up? (do)", "options": ["does", "do", "is"], "answer": 1},
    ],
    "频率": [
        {"question": "I go swimming ___ a week. (two)", "options": ["twice", "two time", "second"], "answer": 0},
        {"question": "___ do you exercise? - Every day.", "options": ["How many", "How often", "What time"], "answer": 1},
    ],
    "be going to": [
        {"question": "What ___ you ___ to do tomorrow? (plan)", "options": ["are, going", "do, want", "did, going"], "answer": 0},
    ],
    "一般过去时": [
        {"question": "I ___ to Beijing last year. (go)", "options": ["go", "went", "going"], "answer": 1},
        {"question": "___ you ___ your homework yesterday?", "options": ["Did, do", "Do, did", "Does, do"], "answer": 0},
    ],
    "名词性物主代词": [
        {"question": "This is my book. It's ___ .", "options": ["mine", "my", "me"], "answer": 0},
        {"question": "Is this ___ bag? - No, it's hers.", "options": ["your", "yours", "you"], "answer": 0},
    ],
    "祈使句": [
        {"question": "___ late! It's impolite.", "options": ["Don't be", "Not be", "Be not"], "answer": 0},
    ],
}

# ==================== 启动时预生成TTS音频 ====================
def pregenerate_all_tts():
    """预生成所有电子书和语法音频（仅默认音色, 避免启动时磁盘爆）"""
    import edge_tts
    import asyncio
    import hashlib
    import json

    # 只预生成默认音色, 其他音色按需生成 (节省 5/6 磁盘)
    VOICES = ['en-US-AriaNeural']

    GRAMMAR_EXPLAINATIONS = [
        "Present Progressive: Subject plus am, is, are, plus verb-ing.",
        "This tense describes an action happening right now.",
        "Simple Present: Subject plus verb s or es.",
        "This tense describes habits and regular actions.",
        "Simple Past: Subject plus verb-ed.",
        "This tense describes actions that happened in the past.",
        "be going to: Subject plus am, is, are, going to plus verb.",
        "This expresses future plans.",
    ]

    async def generate():
        audio_dir = Path(__file__).parent / 'audio' / 'tts'
        audio_dir.mkdir(parents=True, exist_ok=True)

        books_dir = Path(__file__).parent / 'data' / 'books'

        # 1. 遍历所有电子书
        print("📚 正在预生成电子书音频...")
        for book_file in books_dir.glob('*.json'):
            try:
                book_data = json.loads(book_file.read_text())
                sentences_count = 0

                for chapter in book_data.get("chapters", []):
                    for sent in chapter.get("sentences", []):
                        text = sent["text"] if isinstance(sent, dict) else sent
                        if not text or len(text) > 500:
                            continue

                        sentences_count += 1

                        for voice in VOICES:
                            text_hash = hashlib.md5((text + voice).encode()).hexdigest()[:12]
                            audio_path = audio_dir / f'{text_hash}.mp3'
                            if not audio_path.exists():
                                try:
                                    await edge_tts.Communicate(text, voice=voice).save(str(audio_path))
                                except Exception:
                                    pass

                print(f"  ✅ {book_data.get('book', book_file.stem)[:40]}: {sentences_count}句")

            except Exception as e:
                print(f"  ❌ {book_file}: {e}")

        # 2. 生成语法讲解音频
        print("📝 正在预生成语法讲解音频...")
        for grammar_text in GRAMMAR_EXPLAINATIONS:
            for voice in VOICES:
                text_hash = hashlib.md5((grammar_text + voice).encode()).hexdigest()[:12]
                audio_path = audio_dir / f'{text_hash}.mp3'
                if not audio_path.exists():
                    try:
                        await edge_tts.Communicate(grammar_text, voice=voice).save(str(audio_path))
                    except Exception:
                        pass

        print("🎉 所有TTS音频预生成完成！")

    try:
        asyncio.run(generate())
    except Exception as e:
        print(f"Pre-generate error: {e}")

# 启动时预生成（延迟执行，不阻塞服务器启动）
import threading
def start_tts_pregeneration():
    t = threading.Thread(target=pregenerate_all_tts, daemon=True)
    t.start()

# 立即启动预生成（后台线程，不阻塞）
start_tts_pregeneration()

# ==================== 路由 ====================

@app.route('/')
def index():
    return send_html('ebook.html')

@app.route('/tutor')
def tutor_page():
    """跟读辅导页面"""
    return send_html('tutor.html')

@app.route('/grammar/<page>')
def grammar_page(page):
    """语法学习页面"""
    return send_html(page)

@app.route('/grammar')
def grammar_index():
    """语法学习首页"""
    return send_html('grammar.html')

@app.route('/ebook')
def ebook_page():
    """电子书阅读页面"""
    return send_html('ebook.html')

@app.route('/parent')
def parent_page():
    """家长监控页面"""
    return send_html('parent.html')

@app.route('/theme.js')
def theme_js():
    return send_from_directory(str(Path(__file__).parent / 'web'), 'theme.js')

@app.route('/sync.js')
def sync_js():
    return send_from_directory(str(Path(__file__).parent / 'web'), 'sync.js')

@app.route('/a11y.js')
def a11y_js():
    return send_from_directory(str(Path(__file__).parent / 'web'), 'a11y.js')

@app.route('/kid-touch.css')
def kid_touch_css():
    return send_from_directory(str(Path(__file__).parent / 'web'), 'kid-touch.css')

@app.route('/fonts/fonts.css')
def fonts_css():
    return send_from_directory(str(Path(__file__).parent / 'web' / 'fonts'), 'fonts.css')

@app.route('/fonts/<path:filename>')
def font_file(filename):
    return send_from_directory(str(Path(__file__).parent / 'web' / 'fonts'), filename)

@app.route('/manifest.json')
def manifest():
    """PWA manifest"""
    return send_from_directory(str(Path(__file__).parent / 'web'), 'manifest.json')

@app.route('/service-worker.js')
def service_worker():
    """Service Worker"""
    return send_from_directory(str(Path(__file__).parent / 'web'), 'service-worker.js')

@app.route('/icon-<int:size>.png')
@app.route('/screenshot.png')
def icon_or_screenshot(size=None):
    """PWA 图标和截图 — manifest 和 apple-touch-icon 都期望根路径。

    Flask static_folder='web' 把 web/ 挂在 /web/ 路径下，但 manifest.json
    和 service-worker.js 都引用 /icon-*.png 根路径，所以显式路由一下。
    """
    filename = f'icon-{size}.png' if size else 'screenshot.png'
    return send_from_directory(str(Path(__file__).parent / 'web'), filename)

@app.route('/stats')
def stats_page():
    """学习统计页面"""
    return send_html('stats.html')

@app.route('/api/course')
def get_course():
    """获取课程内容"""
    return jsonify({"success": True, "course": COURSE_CONTENT})

@app.route('/api/unit/<int:unit_id>')
def get_unit(unit_id):
    """获取指定单元"""
    if 0 <= unit_id < len(COURSE_CONTENT["units"]):
        return jsonify({"success": True, "unit": COURSE_CONTENT["units"][unit_id]})
    return jsonify({"success": False, "error": "单元不存在"})

@app.route('/api/sentences/<int:unit_id>')
def get_sentences(unit_id):
    """获取单元句子"""
    if 0 <= unit_id < len(COURSE_CONTENT["units"]):
        return jsonify({"success": True, "sentences": COURSE_CONTENT["units"][unit_id]["sentences"]})
    return jsonify({"success": False, "error": "单元不存在"})

@app.route('/api/question/<topic>')
def get_question(topic):
    """获取理解题"""
    questions = COMPREHENSION_QUESTIONS.get(topic, [])
    if questions:
        import random
        q = random.choice(questions)
        return jsonify({"success": True, "question": q})
    return jsonify({"success": False, "error": "没有相关题目"})

@app.route('/api/tts', methods=['POST'])
def text_to_speech():
    """TTS语音合成 - 使用 edge-tts，缓存到本地"""
    data = request.get_json()
    text = data.get('text', '')
    voice = data.get('voice', 'en-US-AriaNeural')  # 默认Aria

    if not text:
        return jsonify({"success": False, "error": "文本为空"})

    # 生成唯一文件名（包含音色的hash）
    import hashlib
    text_hash = hashlib.md5((text + voice).encode()).hexdigest()[:12]
    audio_dir = Path(__file__).parent / 'audio' / 'tts'
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / f'{text_hash}.mp3'

    # 如果已存在则直接返回
    if audio_path.exists():
        return jsonify({"success": True, "audio_url": f"/audio/tts/{text_hash}.mp3"})

    # 使用 edge-tts Python API 生成音频
    import edge_tts
    import asyncio

    async def generate():
        try:
            await edge_tts.Communicate(text, voice=voice).save(str(audio_path))
            return True
        except Exception as e:
            print(f"TTS error: {e}")
            return False

    try:
        asyncio.run(generate())
    except Exception as e:
        return jsonify({"success": False, "error": f"TTS生成失败: {str(e)}"})

    if audio_path.exists():
        return jsonify({"success": True, "audio_url": f"/audio/tts/{text_hash}.mp3"})
    return jsonify({"success": False, "error": "TTS生成失败"})

@app.route('/api/book/<book_id>')
def get_book(book_id):
    """获取书籍内容"""
    book_path = safe_book_path(book_id)
    if book_path is None:
        return jsonify({"success": False, "error": "非法书籍ID"}), 400
    if not book_path.exists():
        return jsonify({"success": False, "error": "书籍不存在"}), 404
    return jsonify({"success": True, "book": json.loads(book_path.read_text())})

# list_books 缓存: mtime-based, books 目录或任一 book JSON 变更时自动失效
_BOOKS_CACHE = {"key": None, "result": None}

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

@app.route('/api/books')
def list_books():
    """列出所有已导入的书籍 (有 mtime 缓存)"""
    books_dir = Path(__file__).parent / 'data' / 'books'
    books_dir.mkdir(parents=True, exist_ok=True)

    # 缓存命中: 目录和文件 mtime 没变就复用
    key = _books_cache_key(books_dir)
    if key is not None and key == _BOOKS_CACHE["key"]:
        return jsonify({"success": True, "books": _BOOKS_CACHE["result"]})

    def calc_lexile(book_data):
        """根据书名估算蓝思值（因为句子数据不完整）"""
        import re
        title = book_data.get('book', '').lower()

        # 已知蓝思值的书籍（更精确的值）
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

        # 查找匹配（统一将下划线转为空格进行匹配）
        title_normalized = title.replace('_', ' ')
        for key, lexile in known_books.items():
            if key in title_normalized:
                return lexile

        # 通用估算：计算句子平均长度
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

        # 根据句子长度估算（经验公式）
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
            print(f"⚠️ 加载书籍失败 {f.stem}: {e}")

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
    import zipfile
    import re
    import html
    from werkzeug.utils import secure_filename

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
        import io
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
                            books_covers_dir = Path(__file__).parent / 'data' / 'covers'
                            books_covers_dir.mkdir(parents=True, exist_ok=True)
                            book_id_for_cover = re.sub(r'[^a-zA-Z0-9_-]', '_', filename.replace('.epub', '').lower())
                            ext = pattern.split('.')[-1].lower()
                            cover_filename = f'{book_id_for_cover}.{ext}'
                            cover_path = books_covers_dir / cover_filename
                            with open(cover_path, 'wb') as f:
                                f.write(img_data)
                            cover_path = f'/data/covers/{cover_filename}'
                            print(f'封面已提取: {cover_filename}')
                            break
                    except Exception as e:
                        print(f'尝试封面图案失败: {e}')
                        continue
            except Exception as e:
                print(f'提取封面出错: {e}')

            # 尝试从 content.opf 读取 spine 顺序
            spine_items = []
            try:
                # 重新读取 content.opf（因为上面的代码可能修改了变量）
                content_opf = zf.read('OEBPS/content.opf').decode('utf-8')
                # 提取 spine 中的 idref
                spine_ids = re.findall(r'<itemref[^>]+idref=["\']([^"\']+)["\']', content_opf)
                # 提取 id 到文件名映射
                id_to_file = dict(re.findall(r'<item[^>]+id=["\']([^"\']+)["\'][^>]+href=["\']([^"\']+)["\']', content_opf))
                spine_items = [id_to_file.get(sid, '') for sid in spine_ids if sid in id_to_file]
            except Exception as e:
                print(f'解析spine顺序失败: {e}')

            # 按 spine 顺序处理文件，没有 spine 则按文件名排序
            ordered_files = spine_items if spine_items else sorted(html_files)

            current_chapter = None
            current_sentences = []

            def clean_text(text):
                """清理 HTML 标签，提取纯文本"""
                # 解码 HTML 实体
                text = html.unescape(text)
                # 移除所有 HTML 标签
                text = re.sub(r'<[^>]+>', ' ', text)
                # 移除多余空白
                text = re.sub(r'\s+', ' ', text).strip()
                return text

            def split_sentences(text):
                """将文本拆分成句子
                智能分句: 避开称谓缩写 (Mr./Dr./Mrs.) / 国家缩写 (U.S.A.) / 数字小数点 / 省略号
                """
                import re as _re
                # 1. 先保护"非句末"的点 - 用占位符替换, 分完句再还原
                PLACEHOLDER = '\x00'
                # 称谓: Mr. Dr. Mrs. Ms. Prof. Sr. Jr. St. Mt. vs. etc.
                text = _re.sub(r'\b(Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|Mt|vs|etc)\.', r'\1' + PLACEHOLDER, text)
                # 单字母缩写序列: U.S.A. / U.K. / U.S.
                text = _re.sub(r'\b([A-Z])\.', r'\1' + PLACEHOLDER, text)
                # 数字小数点: 1.5  2.0  3.14
                text = _re.sub(r'(\d)\.(\d)', r'\1' + PLACEHOLDER + r'\2', text)
                # 省略号: ...
                text = text.replace('...', PLACEHOLDER * 3)

                # 2. 按真正的句末标点切分 (句末 + 空白 + 大写/引号/左括号 = 新句开始)
                parts = _re.split(r'(?<=[.!?])\s+(?=[A-Z"\'(])', text)

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

            # 如果没识别出章节，把每 50 句合成一章
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
                        print(f'解析HTML章节失败: {e}')
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
        book_path = Path(__file__).parent / 'data' / 'books' / f'{book_id}.json'
        book_data = {
            "book": book_title,
            "id": book_id,
            "chapters": merged_chapters,
            "cover": cover_path  # 如果提取到封面会有值
        }
        book_path.parent.mkdir(parents=True, exist_ok=True)
        book_path.write_text(json.dumps(book_data, ensure_ascii=False, indent=2))

        return jsonify({
            "success": True,
            "book_id": book_id,
            "book_title": book_title,
            "total_chapters": len(merged_chapters),
            "total_sentences": total_sentences,
            "has_cover": cover_path is not None
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": "导入失败: " + type(e).__name__})

@app.route('/data/covers/<path:filename>')
def serve_covers(filename):
    """提供封面图片"""
    covers_dir = Path(__file__).parent / 'data' / 'covers'
    return send_from_directory(covers_dir, filename)

# ==================== 家长鉴权 (server-side PIN) ====================
# 之前 PIN 检查只在浏览器, 任何人访问 /parent 都能看 stats。
# 现在 PIN 校验在 server 端, session 走 HttpOnly cookie。
# 孩子端页面继续 anon 上报 stats / vocab 到 server, 家长 dashboard 走鉴权读。

PIN_FILE = PARENT_DATA_DIR / 'pin.hash'
PARENT_DATA_FILE = PARENT_DATA_DIR / 'data.json'

def _hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode('utf-8')).hexdigest()

def _load_pin_hash() -> str:
    """读取 PIN 哈希, 首次运行写入默认 0000"""
    if PIN_FILE.exists():
        return PIN_FILE.read_text().strip()
    default = _hash_pin('0000')
    PIN_FILE.write_text(default)
    print('🔐 家长 PIN 首次初始化: 默认 0000, 请尽快修改', file=sys.stderr)
    return default

def _check_pin(pin: str) -> bool:
    return _hash_pin(str(pin)) == _load_pin_hash()

def _load_parent_data() -> dict:
    if PARENT_DATA_FILE.exists():
        try:
            return json.loads(PARENT_DATA_FILE.read_text())
        except Exception:
            pass
    return {"stats": {}, "vocabulary": {}, "settings": {}}

def _save_parent_data(data: dict):
    PARENT_DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))

@app.route('/api/parent/check')
def parent_check():
    return jsonify({"authenticated": bool(session.get('parent_auth'))})

@app.route('/api/parent/login', methods=['POST'])
def parent_login():
    ip = request.remote_addr or 'unknown'
    ok, retry = _login_rate_limit_ok(ip)
    if not ok:
        return jsonify({"success": False, "error": f"尝试次数过多, 请 {retry} 秒后再试"}), 429

    data = request.json or {}
    pin = str(data.get('pin', '')).strip()
    if not (pin.isdigit() and len(pin) == 4):
        _login_record_failure(ip)
        return jsonify({"success": False, "error": "PIN 必须是 4 位数字"}), 400
    if not _check_pin(pin):
        _login_record_failure(ip)
        return jsonify({"success": False, "error": "PIN 错误"}), 401
    _login_clear(ip)
    session['parent_auth'] = True
    session.permanent = True
    return jsonify({"success": True})

@app.route('/api/parent/logout', methods=['POST'])
@require_parent_auth
def parent_logout():
    session.pop('parent_auth', None)
    return jsonify({"success": True})

@app.route('/api/parent/change-pin', methods=['POST'])
@require_parent_auth
def parent_change_pin():
    data = request.json or {}
    current = str(data.get('current', '')).strip()
    new = str(data.get('new', '')).strip()
    if not _check_pin(current):
        return jsonify({"success": False, "error": "当前 PIN 错误"}), 401
    if not (new.isdigit() and len(new) == 4):
        return jsonify({"success": False, "error": "新 PIN 必须是 4 位数字"}), 400
    PIN_FILE.write_text(_hash_pin(new))
    return jsonify({"success": True})

@app.route('/api/parent/data', methods=['GET'])
@require_parent_auth
def parent_get_data():
    return jsonify({"success": True, "data": _load_parent_data()})

@app.route('/api/parent/data', methods=['POST'])
def parent_post_data():
    """孩子端 anon 上报 stats/vocab/settings, 不需要鉴权
    (合并写入, 不会覆盖整个文件)"""
    payload = request.json or {}
    current = _load_parent_data()
    for section in ('stats', 'vocabulary', 'settings'):
        if section in payload and isinstance(payload[section], dict):
            current.setdefault(section, {}).update(payload[section])
    _save_parent_data(current)
    return jsonify({"success": True})

@app.route('/api/parent/reset', methods=['POST'])
@require_parent_auth
def parent_reset():
    _save_parent_data({"stats": {}, "vocabulary": {}, "settings": {}})
    return jsonify({"success": True})

@app.route('/api/parent/export')
@require_parent_auth
def parent_export():
    from flask import Response
    payload = json.dumps(_load_parent_data(), ensure_ascii=False, indent=2)
    return Response(
        payload,
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment; filename=shadow_learning_data.json'}
    )

@app.route('/audio/<path:filename>')
def serve_audio(filename):
    """提供音频文件"""
    audio_dir = Path(__file__).parent / 'audio'
    return send_from_directory(audio_dir, filename)

# ==================== 启动 ====================

if __name__ == '__main__':
    import socket

    def get_lan_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "localhost"

    lan_ip = get_lan_ip()

    # HTTPS 自签名证书（iOS Safari getUserMedia 需要 secure context）
    cert_path = Path(__file__).parent / 'certs' / 'server.crt'
    key_path = Path(__file__).parent / 'certs' / 'server.key'
    ssl_ctx = None
    if cert_path.exists() and key_path.exists():
        ssl_ctx = (str(cert_path), str(key_path))
        print("🔐 HTTPS 模式（自签名证书）")
    else:
        print("⚠️  HTTP 模式 — 麦克风在 iOS Safari 上不可用")
        print("   生成证书: bash scripts/gen_https_cert.sh")

    print("🦊 Shadow Learning - 原版阅读社团版")
    print("=" * 50)
    scheme = 'https' if ssl_ctx else 'http'
    print(f"🌐 本机访问: {scheme}://localhost:5002")
    print(f"📱 局域网访问: {scheme}://{lan_ip}:5002")
    print()
    print("让小朋友在浏览器打开上面的局域网地址")
    print()

    app.run(host='0.0.0.0', port=5002, debug=False, ssl_context=ssl_ctx)
