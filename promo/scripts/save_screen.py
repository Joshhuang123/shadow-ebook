#!/usr/bin/env python3
"""「可保存的那一屏」:一张孩子读错音时的对照表。

skill 的要求:片尾要给一个**能整屏放下的表/清单** + 一句明确的保存理由。
这张表的内容全部来自项目自己的音素提示语(extensions/phonemes.py),
不是另编的一套 —— 视频里说「/AO/ 还不稳」,表里就是同一句「长 o 像 go」。
"""
import base64
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import CDP, launch, new_tab  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "封面")
os.makedirs(OUT, exist_ok=True)

ROWS = [
    ("F", "fish", "上齿轻咬下唇,气从缝里挤出来"),
    ("TH", "think", "舌尖轻放在上下齿之间,气从缝里挤"),
    ("SH", "ship", "嘴唇像吹蜡烛一样圆起,气从缝里出"),
    ("L", "look", "舌尖顶住上齿龈,气从舌头两边流出"),
    ("R", "red", "舌尖卷起来,但不碰到任何地方"),
    ("V", "van", "上齿轻咬下唇,喉咙要振动"),
    ("CH", "chair", "舌尖顶上齿龈再摩擦,气从缝里出"),
    ("S", "sun", "舌尖靠近上齿龈,气从缝里「嘶」出来"),
    ("Z", "zoo", "舌尖靠近上齿龈,喉咙要振动"),
    ("W", "water", "双唇收圆往前送,再放开"),
    ("AO", "go", "长 o"),
    ("ER", "bird", "卷舌 er"),
]

CSS = """
*{margin:0;padding:0;box-sizing:border-box;}
body{background:#F4F1EA;}
.cover{
  position:relative;overflow:hidden;width:1080px;height:1440px;
  background:
    radial-gradient(1000px 560px at 84% -6%, rgba(212,165,116,.13) 0%, transparent 62%),
    linear-gradient(160deg,#F8F5EF 0%,#EDE6D9 100%);
  font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Helvetica Neue','Segoe UI',Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;color:#2D2A26;padding:72px 68px;
}
.eyebrow{display:flex;align-items:center;gap:10px;font-size:22px;font-weight:600;
  letter-spacing:.2em;color:#B86A4E;margin-bottom:22px;}
.eyebrow i{width:9px;height:9px;border-radius:50%;background:#B86A4E;display:block;}
h1{font-family:'Iowan Old Style','Palatino',Georgia,'Songti SC Black','STSongti-SC-Black',
  'Songti SC','STSong','SimSun','Source Han Serif SC','Noto Serif CJK SC',serif;
  font-weight:700;font-size:60px;line-height:1.16;letter-spacing:-.015em;margin-bottom:18px;}
.rule{height:3px;background:linear-gradient(90deg,#B86A4E 0%,rgba(184,106,78,0) 78%);
  width:280px;margin-bottom:12px;}
.lead{font-size:25px;color:#5A544C;line-height:1.65;font-weight:300;margin-bottom:26px;}
table{width:100%;border-collapse:collapse;}
td{padding:13px 0;border-bottom:1px solid rgba(45,42,38,.10);vertical-align:middle;}
td.ph{width:230px;white-space:nowrap;}
.tag{display:inline-block;font-family:'SF Mono',Menlo,Consolas,monospace;font-size:26px;
  color:#A55A40;letter-spacing:.02em;}
.ex{font-size:21px;color:#8A857C;margin-left:10px;white-space:nowrap;}
.how{font-size:24px;color:#3A3733;line-height:1.45;}
.sign{position:absolute;left:68px;right:68px;bottom:64px;padding-top:22px;
  border-top:1px solid rgba(45,42,38,.12);display:flex;align-items:center;
  justify-content:space-between;font-size:21px;color:#5A544C;}
.save{color:#B86A4E;font-weight:600;}
"""


def main():
    rows = "".join(
        f'<tr><td class="ph"><span class="tag">/{p}/</span>'
        f'<span class="ex">像 {ex}</span></td>'
        f'<td class="how">{how}</td></tr>' for p, ex, how in ROWS)
    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head>
<body><div class="cover">
  <div class="eyebrow"><i></i><span>影子电子书 · 跟读评分</span></div>
  <h1>孩子读错这些音<br>照着这张表纠</h1>
  <div class="rule"></div>
  <p class="lead">跟读评分会直接指出是哪个音还不稳。这张表是那 12 个音<br>的嘴型说明,存在手机里,他自己练就行。</p>
  <table>{rows}</table>
  <div class="sign"><span>影子电子书 · 一台电脑服务全家平板</span>
    <span class="save">存下来,他自己练</span></div>
</div></body></html>"""
    path = "/tmp/save-screen.html"
    open(path, "w").write(html)
    proc = launch(port=9710, profile="/tmp/chrome-save", width=1080, height=1440)
    try:
        tab = new_tab(port=9710, url="file://" + path)
        cdp = CDP(tab["webSocketDebuggerUrl"])
        cdp.call("Runtime.enable")
        cdp.call("Page.enable")
        cdp.call("Emulation.setDeviceMetricsOverride", {
            "width": 1080, "height": 1440, "deviceScaleFactor": 1, "mobile": False})
        cdp.call("Page.navigate", {"url": "file://" + path})
        time.sleep(1.5)
        shot = cdp.call("Page.captureScreenshot", {"format": "png"})
        out = f"{OUT}/可保存的那一屏.png"
        with open(out, "wb") as f:
            f.write(base64.b64decode(shot["data"]))
        print("saved", out)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
