"""
Owns: PWA shell assets — theme/sync/a11y JS, kid-touch CSS, fonts, manifest, service-worker, icons.
Does NOT own: HTML page routes (app.py), domain-specific static files (audio in tts.py, covers in books.py).
"""
from pathlib import Path
from flask import send_from_directory


WEB_DIR = Path(__file__).resolve().parent.parent / 'web'
FONTS_DIR = WEB_DIR / 'fonts'

# 根路径暴露的静态资源 (manifest/service-worker 引用 /theme.js 而非 /web/theme.js)
# - key   = URL 路径
# - value = (目录, 文件名 or None=透传)
# icons / screenshot 单独处理因为 <int:size> 转换器
_ROOT_STATIC = [
    ('/theme.js',         WEB_DIR,  'theme.js'),
    ('/sync.js',          WEB_DIR,  'sync.js'),
    ('/a11y.js',          WEB_DIR,  'a11y.js'),
    ('/kid-touch.css',    WEB_DIR,  'kid-touch.css'),
    ('/fonts/fonts.css',  FONTS_DIR, 'fonts.css'),
    ('/manifest.json',    WEB_DIR,  'manifest.json'),
]


def register_routes(app):
    for url, directory, filename in _ROOT_STATIC:
        app.add_url_rule(
            url, endpoint=f'pwa_{filename}',  # 唯一 endpoint 名
            view_func=lambda d=directory, f=filename: send_from_directory(str(d), f),
        )

    @app.route('/fonts/<path:filename>')
    def font_file(filename):
        return send_from_directory(str(FONTS_DIR), filename)

    @app.route('/service-worker.js')
    def service_worker():
        """Service Worker — 需 Service-Worker-Allowed: / 头让 SW 控制根域"""
        resp = send_from_directory(str(WEB_DIR), 'service-worker.js')
        resp.headers['Service-Worker-Allowed'] = '/'
        return resp

    @app.route('/icon-<int:size>.png')
    @app.route('/screenshot.png')
    def icon_or_screenshot(size=None):
        """PWA 图标和截图 — manifest 和 apple-touch-icon 都期望根路径。

        Flask static_folder='web' 把 web/ 挂在 /web/ 路径下,但 manifest.json
        和 service-worker.js 都引用 /icon-*.png 根路径,所以显式路由一下。
        """
        filename = f'icon-{size}.png' if size else 'screenshot.png'
        return send_from_directory(str(WEB_DIR), filename)
