#!/usr/bin/env python3
"""
Shadow Learning - 英语跟读辅导系统
显示句子 → TTS朗读 → 孩子跟读 → 评价反馈 → 理解题测试

App 入口。每个域在 extensions/*.py,通过 register_routes(app) 挂路由。
HTML 页面路由(无业务逻辑的"壳"页面)直接在本文件定义。
"""
import logging
import os
import secrets
import socket
from pathlib import Path

from flask import Flask, send_from_directory

from extensions import pwa, courses, tts, books, parent_data, db


WEB_DIR = Path(__file__).parent / 'web'
DATA_DIR = Path(__file__).parent / 'data'
LOG_FILE = DATA_DIR / 'shadow.log'


# === Phase 2 加 logging: stdout + 文件 双输出 ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(LOG_FILE)),
    ],
)


# === Phase 3: SQLite init (首次启动建表 + 一次性 JSON→SQLite 迁移) ===
db.init_db()


def _send_html(filename):
    """统一返回 HTML 文件,避免路径拼接问题"""
    return send_from_directory(str(WEB_DIR), filename)


app = Flask(__name__, template_folder='web', static_folder='web')
app.config['SECRET_KEY'] = os.environ.get('SHADOW_SECRET', secrets.token_hex(32))
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB 上传上限
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'


# === HTML 页面路由 (壳页面,无业务逻辑) ===
@app.route('/')
def index():
    return _send_html('ebook.html')

@app.route('/tutor')
def tutor_page():
    """跟读辅导页面"""
    return _send_html('tutor.html')

@app.route('/grammar')
def grammar_index():
    """语法学习首页"""
    return _send_html('grammar.html')

@app.route('/grammar/<page>')
def grammar_page(page):
    """语法学习页面"""
    return _send_html(page)

@app.route('/ebook')
def ebook_page():
    """电子书阅读页面"""
    return _send_html('ebook.html')

@app.route('/parent')
def parent_page():
    """家长监控页面"""
    return _send_html('parent.html')

@app.route('/stats')
def stats_page():
    """学习统计页面"""
    return _send_html('stats.html')


# === 注册各域路由 ===
pwa.register_routes(app)
courses.register_routes(app)
tts.register_routes(app)
books.register_routes(app)
parent_data.register_routes(app)
db.register_routes(app)


# === 启动 ===
if __name__ == '__main__':
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

    # HTTPS 自签名证书(iOS Safari getUserMedia 需要 secure context)
    cert_path = Path(__file__).parent / 'certs' / 'server.crt'
    key_path = Path(__file__).parent / 'certs' / 'server.key'
    ssl_ctx = None
    if cert_path.exists() and key_path.exists():
        ssl_ctx = (str(cert_path), str(key_path))
        print("🔐 HTTPS 模式(自签名证书)")
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

    # 启动 TTS 预生成(后台线程,不阻塞)
    # 显式调用,不在 import 时启动 (避免 import app 时触发后台线程)
    tts.start_tts_pregeneration()

    app.run(host='0.0.0.0', port=5002, debug=False, ssl_context=ssl_ctx)