#!/usr/bin/env python3
"""
一次性验证 (R17): 启动 Flask,Playwright headless 浏览器加载 5 页,
点 themeBtn 切深浅色,验证 body bg 颜色变化。
"""
import os
import sys
import time
import socket
import subprocess
import urllib.request

from playwright.sync_api import sync_playwright

PORT = 5555

def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

def start_app():
    env = os.environ.copy()
    env['FLASK_PORT'] = str(PORT)
    p = subprocess.Popen(
        [sys.executable, '-c', f'''
import sys
sys.path.insert(0, "/Users/huangjunhai/shadow-learning")
from app import app
app.run(host="127.0.0.1", port={PORT}, debug=False, use_reloader=False)
'''],
        cwd='/Users/huangjunhai/shadow-learning',
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    # 等服务起来
    for _ in range(30):
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{PORT}/healthz', timeout=1)
            return p
        except Exception:
            time.sleep(0.3)
    p.terminate()
    raise RuntimeError('app did not start in 9 seconds')

def hex_to_rgb(s):
    """ 'rgb(245, 237, 229)' → (245, 237, 229); 'rgba(0,0,0,0)' → (0,0,0) '"""
    if not s:
        return None
    if s.startswith('#'):
        s = s.lstrip('#')
        return tuple(int(s[i:i+2], 16) for i in (0, 2, 4))
    if 'rgb' in s:
        # 去掉 'rgb(' / 'rgba(' 前缀和 ')'
        inner = s[s.index('(')+1 : s.index(')')]
        nums = [int(x.strip()) for x in inner.split(',') if x.strip()]
        return tuple(nums[:3])
    return None

def parse_gradient_brightness(gradient_str):
    """ 'linear-gradient(135deg, rgb(245, 237, 229) 0%, rgb(237, 227, 214) 100%)' → 亮度 """
    if not gradient_str or 'gradient' not in gradient_str:
        return None
    import re as _re
    colors = _re.findall(r'(?:#[0-9a-fA-F]{3,6}|rgba?\([^)]+\))', gradient_str)
    if not colors:
        return None
    rgb = hex_to_rgb(colors[0])
    return lightness(rgb)

def lightness(rgb):
    if not rgb: return None
    r, g, b = rgb
    return (0.299*r + 0.587*g + 0.114*b) / 255

def main():
    proc = start_app()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for path in ['/', '/tutor', '/grammar', '/stats']:  # parent.html 没有 themeBtn
                    page = browser.new_page()
                    page.goto(f'http://127.0.0.1:{PORT}{path}')
                    page.wait_for_load_state('networkidle')

                    # Force into light first
                    page.evaluate("localStorage.setItem('shTheme', 'day'); document.documentElement.dataset.theme = 'light';")
                    page.reload()
                    page.wait_for_load_state('networkidle')

                    # 用 background-image 抓渐变,fallback 用 background-color
                    bg_light_str = page.evaluate('() => getComputedStyle(document.body).backgroundImage')
                    bg_light_color = page.evaluate('() => getComputedStyle(document.body).backgroundColor')
                    light_l = parse_gradient_brightness(bg_light_str)
                    if light_l is None:
                        rgb = hex_to_rgb(bg_light_color)
                        light_l = lightness(rgb) if rgb else None

                    # Force into dark
                    page.evaluate("localStorage.setItem('shTheme', 'night'); document.documentElement.dataset.theme = 'dark';")
                    page.wait_for_timeout(300)

                    bg_dark_str = page.evaluate('() => getComputedStyle(document.body).backgroundImage')
                    bg_dark_color = page.evaluate('() => getComputedStyle(document.body).backgroundColor')
                    dark_l = parse_gradient_brightness(bg_dark_str)
                    if dark_l is None:
                        rgb = hex_to_rgb(bg_dark_color)
                        dark_l = lightness(rgb) if rgb else None
                    theme_attr = page.evaluate('() => document.documentElement.dataset.theme')

                    l_str = f'{light_l:.2f}' if light_l is not None else 'NA'
                    d_str = f'{dark_l:.2f}' if dark_l is not None else 'NA'
                    delta = (light_l - dark_l) if (light_l and dark_l) else None
                    ok = (light_l is not None and dark_l is not None
                          and delta > 0.3)
                    marker = '✓' if ok else '✗'
                    delta_str = f'{delta:.2f}' if delta is not None else 'NA'
                    print(f'{marker} {path:10s} light={l_str}  dark={d_str}  (Δ={delta_str})  theme={theme_attr!r}')

                    page.close()
            finally:
                browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

if __name__ == '__main__':
    main()
