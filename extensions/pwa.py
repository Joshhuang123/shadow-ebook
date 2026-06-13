"""
Owns: PWA shell assets — theme/sync/a11y JS, kid-touch CSS, fonts, manifest, service-worker, icons.
Does NOT own: HTML page routes (app.py), domain-specific static files (audio in tts.py, covers in books.py).
"""
from pathlib import Path
from flask import send_from_directory


WEB_DIR = Path(__file__).resolve().parent.parent / 'web'
FONTS_DIR = WEB_DIR / 'fonts'


def register_routes(app):
    @app.route('/theme.js')
    def theme_js():
        return send_from_directory(str(WEB_DIR), 'theme.js')

    @app.route('/sync.js')
    def sync_js():
        return send_from_directory(str(WEB_DIR), 'sync.js')

    @app.route('/a11y.js')
    def a11y_js():
        return send_from_directory(str(WEB_DIR), 'a11y.js')

    @app.route('/kid-touch.css')
    def kid_touch_css():
        return send_from_directory(str(WEB_DIR), 'kid-touch.css')

    @app.route('/fonts/fonts.css')
    def fonts_css():
        return send_from_directory(str(FONTS_DIR), 'fonts.css')

    @app.route('/fonts/<path:filename>')
    def font_file(filename):
        return send_from_directory(str(FONTS_DIR), filename)

    @app.route('/manifest.json')
    def manifest():
        """PWA manifest"""
        return send_from_directory(str(WEB_DIR), 'manifest.json')

    @app.route('/service-worker.js')
    def service_worker():
        """Service Worker"""
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