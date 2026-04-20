#!/usr/bin/env python3
"""
Shadow Learning - 英语跟读辅导系统
显示句子 → TTS朗读 → 孩子跟读 → 评价反馈 → 理解题测试
"""
import os
import sys
import json
from pathlib import Path
from flask import Flask, render_template, jsonify, request, send_from_directory

app = Flask(__name__, template_folder='web', static_folder='web')

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

# ==================== 路由 ====================

@app.route('/')
def index():
    return send_from_directory(app.root_path + '/web', 'ebook.html')

@app.route('/tutor')
def tutor_page():
    """跟读辅导页面"""
    return send_from_directory(app.root_path + '/web', 'tutor.html')

@app.route('/grammar/<page>')
def grammar_page(page):
    """语法学习页面"""
    return send_from_directory(app.root_path + '/web', page)

@app.route('/grammar')
def grammar_index():
    """语法学习首页"""
    return send_from_directory(app.root_path + '/web', 'grammar.html')

@app.route('/ebook')
def ebook_page():
    """电子书阅读页面"""
    return send_from_directory(app.root_path + '/web', 'ebook.html')

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

    if not text:
        return jsonify({"success": False, "error": "文本为空"})

    # 生成唯一文件名（文本的hash）
    import hashlib
    text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
    audio_dir = Path(__file__).parent / 'audio' / 'tts'
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / f'{text_hash}.mp3'

    # 如果已存在则直接返回
    if audio_path.exists():
        return jsonify({"success": True, "audio_url": f"/audio/tts/{text_hash}.mp3"})

    # 使用 edge-tts 生成音频
    import subprocess
    result = subprocess.run([
        'edge-tts',
        '-v', 'en-US-AriaNeural',
        '-t', text,
        '--write-media', str(audio_path)
    ], capture_output=True, text=True, timeout=30)

    if audio_path.exists():
        return jsonify({"success": True, "audio_url": f"/audio/tts/{text_hash}.mp3"})
    return jsonify({"success": False, "error": f"TTS生成失败: {result.stderr}"})

# 预生成所有句子音频
@app.route('/api/tts/pregenerate', methods=['POST'])
def pregenerate_all_tts():
    """预生成所有课程音频"""
    import edge_tts
    import asyncio
    import hashlib

    async def generate():
        audio_dir = Path(__file__).parent / 'audio' / 'tts'
        audio_dir.mkdir(parents=True, exist_ok=True)

        # NC2A 句子
        for unit in COURSE_CONTENT["units"]:
            for sent in unit["sentences"]:
                text = sent["text"] if isinstance(sent, dict) else sent
                text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
                audio_path = audio_dir / f'{text_hash}.mp3'
                if not audio_path.exists():
                    await edge_tts.Communicate(text, voice='en-US-AriaNeural').save(str(audio_path))

        # MTH29 句子
        import json
        mth_path = Path(__file__).parent / 'data' / 'books' / 'christmas_in_camelot.json'
        if mth_path.exists():
            mth_data = json.loads(mth_path.read_text())
            for chapter in mth_data.get("chapters", []):
                for sent in chapter.get("sentences", []):
                    text = sent["text"] if isinstance(sent, dict) else sent
                    text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
                    audio_path = audio_dir / f'{text_hash}.mp3'
                    if not audio_path.exists():
                        await edge_tts.Communicate(text, voice='en-US-AriaNeural').save(str(audio_path))

        return {"success": True, "message": "音频生成完成"}

    try:
        asyncio.run(generate())
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

    return jsonify({"success": True, "message": "音频生成完成"})

@app.route('/api/book/<book_id>')
def get_book(book_id):
    """获取书籍内容"""
    book_path = Path(__file__).parent / 'data' / 'books' / f'{book_id}.json'
    if book_path.exists():
        return jsonify({"success": True, "book": json.loads(book_path.read_text())})
    return jsonify({"success": False, "error": "书籍不存在"})

@app.route('/api/books')
def list_books():
    """列出所有已导入的书籍"""
    books_dir = Path(__file__).parent / 'data' / 'books'
    books_dir.mkdir(parents=True, exist_ok=True)

    books = []
    for f in books_dir.glob('*.json'):
        try:
            data = json.loads(f.read_text())
            total_sentences = sum(len(ch.get('sentences', [])) for ch in data.get('chapters', []))
            books.append({
                "id": f.stem,
                "title": data.get('book', data.get('title', f.stem)),
                "chapters": len(data.get('chapters', [])),
                "sentences": total_sentences
            })
        except:
            pass

    return jsonify({"success": True, "books": books})

@app.route('/api/book/<book_id>', methods=['DELETE'])
def delete_book(book_id):
    """删除书籍"""
    book_path = Path(__file__).parent / 'data' / 'books' / f'{book_id}.json'
    if book_path.exists():
        book_path.unlink()
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "书籍不存在"})

@app.route('/api/book/import', methods=['POST'])
def import_book():
    """导入 EPUB 电子书"""
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

        with zipfile.ZipFile(epub_data, 'r') as zf:
            # 找所有 HTML/XHTML 文件
            html_files = [n for n in zf.namelist() if n.endswith(('.html', '.xhtml', '.htm')) and 'image' not in n.lower()]

            # 尝试从 content.opf 读取 spine 顺序
            spine_items = []
            try:
                content_opf = zf.read('OEBPS/content.opf').decode('utf-8')
                # 提取 spine 中的 idref
                spine_ids = re.findall(r'<itemref[^>]+idref=["\']([^"\']+)["\']', content_opf)
                # 提取 id 到文件名映射
                id_to_file = dict(re.findall(r'<item[^>]+id=["\']([^"\']+)["\'][^>]+href=["\']([^"\']+)["\']', content_opf))
                spine_items = [id_to_file.get(sid, '') for sid in spine_ids if sid in id_to_file]
            except:
                pass

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
                """将文本拆分成句子"""
                # 按句子结束符拆分
                parts = re.split(r'(?<=[.!?])\s+', text)
                sentences = []
                for p in parts:
                    p = p.strip()
                    if len(p) > 10 and len(p.split()) >= 3:  # 过滤太短的内容
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
                    except:
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
            "chapters": merged_chapters
        }
        book_path.parent.mkdir(parents=True, exist_ok=True)
        book_path.write_text(json.dumps(book_data, ensure_ascii=False, indent=2))

        return jsonify({
            "success": True,
            "book_id": book_id,
            "book_title": book_title,
            "total_chapters": len(merged_chapters),
            "total_sentences": total_sentences
        })

    except Exception as e:
        import traceback
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/transcribe', methods=['POST'])
def transcribe_audio():
    """语音识别 - 使用 macOS 内置语音识别"""
    try:
        import speech_recognition as sr
        import tempfile
        import os

        # 保存上传的音频
        audio_file = request.files.get('audio')
        if not audio_file:
            return jsonify({"success": False, "error": "没有音频文件"})

        # 保存为临时文件
        with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
            audio_file.save(tmp.name)
            tmp_path = tmp.name

        try:
            # 使用 speech_recognition 识别
            recognizer = sr.Recognizer()
            with sr.AudioFile(tmp_path) as source:
                audio_data = recognizer.record(source)
                # 使用 macOS 内置语音识别
                text = recognizer.recognize_speech(audio_data, language='en-US')
                return jsonify({"success": True, "text": text})
        finally:
            # 删除临时文件
            os.unlink(tmp_path)

    except ImportError:
        # speech_recognition 未安装，尝试使用 whisper
        try:
            import subprocess
            import tempfile
            import os

            audio_file = request.files.get('audio')
            if not audio_file:
                return jsonify({"success": False, "error": "没有音频文件"})

            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                # 转换格式
                audio_file.save(tmp.name)
                tmp_path = tmp.name

            try:
                # 使用 whisper CLI
                result = subprocess.run(
                    ['whisper', tmp_path, '--language', 'en', '--output_format', 'json'],
                    capture_output=True, text=True, timeout=30
                )
                # 解析 whisper 输出
                import json as json_lib
                try:
                    data = json_lib.loads(result.stdout)
                    text = data.get('text', '').strip()
                    if text:
                        return jsonify({"success": True, "text": text})
                except:
                    pass
                return jsonify({"success": False, "error": "Whisper 识别失败"})
            finally:
                os.unlink(tmp_path)
        except Exception as e:
            return jsonify({"success": False, "error": f"Whisper 也不可用: {str(e)}"})
    except sr.UnknownValueError:
        return jsonify({"success": False, "error": "无法识别语音内容"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/audio/<path:filename>')
def serve_audio(filename):
    """提供音频文件"""
    audio_dir = Path(__file__).parent / 'audio'
    return send_from_directory(audio_dir, filename)

# ==================== 启动 ====================

if __name__ == '__main__':
    print("🦊 英语跟读辅导系统")
    print("=" * 50)
    print("🌐 打开浏览器访问: http://localhost:5002")
    print()

    import webbrowser
    webbrowser.open('http://localhost:5002')

    app.run(host='0.0.0.0', port=5002, debug=False)
