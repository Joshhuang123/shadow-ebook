#!/usr/bin/env python3
"""封面投放包:四画幅 × 三档 = 12 张。

照 josh-media skill 的封面铁律:
  1. **四画幅各自排版**,不是同一版裁切或拉伸:
     竖版堆叠(眉标→主视觉→标题→部署名→角标),
     横版并置(眉标左上→文字左→主视觉右→部署名→角标右下)。
  2. 真实感靠原件:主视觉是**真截图**(不是重画的示意图),旁边标出处。
  3. 时长角标用 **ffprobe 实测值**,不许用估算值。
  4. 每画幅三档:标准 / 高清(2×) / 小图(列表缩略)。

画面语言沿用 App 自己的「纸 + 墨 + 赤陶」,不换成别的系列风格。
"""
import base64
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import CDP, launch, new_tab  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = "/tmp/promo/padded" if os.path.isdir("/tmp/promo/padded") else os.path.join(ROOT, "promo", "padded")
OUT = os.path.join(ROOT, "封面")
os.makedirs(OUT, exist_ok=True)

# 主视觉:真截图(跟读那张最有说服力 —— 界面真的在指出哪个音不对)
HERO = "tutor-feedback-card.png"
HERO_CREDIT = "真实运行截图 · 影子电子书"

TITLE = "孩子读错哪个「音」\n它能指出来"
EYEBROW = "影子电子书 · 局域网里的家庭英语阅读器"
SIGN = "一台电脑服务全家平板 · 数据留在家里"


def img(name):
    p = os.path.join(SHOTS, name)
    if not os.path.exists(p):
        return ""
    return "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()


CSS = """
*{margin:0;padding:0;box-sizing:border-box;}
body{background:#F4F1EA;}
.cover{
  position:relative;overflow:hidden;
  background:
    radial-gradient(1100px 620px at 82% -6%, rgba(212,165,116,.13) 0%, transparent 62%),
    radial-gradient(820px 560px at 4% 102%, rgba(122,139,159,.07) 0%, transparent 60%),
    linear-gradient(160deg,#F8F5EF 0%,#EDE6D9 100%);
  font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Helvetica Neue','Segoe UI',Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;color:#2D2A26;
}
.eyebrow{position:absolute;left:__L__px;top:__T__px;right:__R__px;
  display:flex;align-items:center;gap:10px;
  font-size:__EBS__px;font-weight:600;letter-spacing:.2em;color:#B86A4E;}
.eyebrow i{width:__DOT__px;height:__DOT__px;border-radius:50%;background:#B86A4E;display:block;}
.title{font-family:'Iowan Old Style','Palatino',Georgia,'Songti SC Black','STSongti-SC-Black',
  'Songti SC','STSong','SimSun','Source Han Serif SC','Noto Serif CJK SC',serif;
  font-weight:700;letter-spacing:-.015em;line-height:1.14;white-space:pre-line;}
.rule{height:3px;background:linear-gradient(90deg,#B86A4E 0%,rgba(184,106,78,0) 78%);}
.hero{border-radius:__HR__px;overflow:hidden;background:#FCFBF8;
  border:1px solid rgba(45,42,38,.14);
  box-shadow:0 22px 54px rgba(45,42,38,.15),0 3px 8px rgba(45,42,38,.06);}
.hero img{width:100%;height:100%;object-fit:cover;object-position:center top;display:block;}
.hero.contain img{object-fit:contain;}
.credit{font-size:__CS__px;color:#8A857C;letter-spacing:.02em;}
.sign{position:absolute;left:__L__px;bottom:__B__px;right:__R__px;
  padding-top:__SPT__px;border-top:1px solid rgba(45,42,38,.12);
  display:flex;align-items:center;justify-content:space-between;gap:16px;
  font-size:__SS__px;color:#5A544C;}
.badge{position:absolute;right:__R__px;bottom:__BB__px;
  padding:__BAP__px __BHP__px;border-radius:9999px;
  background:rgba(45,42,38,.9);color:#FCFBF8;font-size:__BFS__px;
  font-family:'SF Mono',Menlo,Consolas,monospace;letter-spacing:.02em;}
"""


def layout_tall(W, H, s):
    """竖 9:16 / 3:4:堆叠 —— 眉标 → 主视觉 → 标题 → 部署名 → 角标。"""
    return f"""
    <div class="eyebrow"><i></i><span>{EYEBROW}</span></div>
    <div class="hero contain" style="position:absolute;left:{s['L']}px;right:{s['R']}px;
         top:{s['HT']}px;height:{s['HH']}px"><img src="{img(HERO)}"></div>
    <div style="position:absolute;left:{s['L']}px;right:{s['R']}px;top:{s['TT']}px">
      <div class="title" style="font-size:{s['TS']}px">{TITLE}</div>
      <div class="rule" style="width:{s['RW']}px;margin-top:{s['RM']}px"></div>
      <div class="credit" style="margin-top:{s['CM']}px">{HERO_CREDIT}</div>
    </div>"""


def layout_wide(W, H, s):
    """横 16:9:并置 —— 眉标左上 → 文字左 → 主视觉右 → 部署名 → 角标右下。

    16:9 高度只有 1080,标题和主视觉不能上下堆 —— 堆了就有一半高度空着,
    所以左右两栏(左主张 / 右证据),两栏收在同一条基线上。
    """
    return f"""
    <div class="eyebrow"><i></i><span>{EYEBROW}</span></div>
    <div style="position:absolute;left:{s['L']}px;top:{s['TT']}px;width:{s['TW']}px">
      <div class="title" style="font-size:{s['TS']}px">{TITLE}</div>
      <div class="rule" style="width:{s['RW']}px;margin-top:{s['RM']}px"></div>
      <div class="credit" style="margin-top:{s['CM']}px">{HERO_CREDIT}</div>
    </div>
    <div class="hero contain" style="position:absolute;left:{s['HL']}px;top:{s['HT']}px;
         width:{s['HW']}px;height:{s['HH']}px"><img src="{img(HERO)}"></div>"""


# 四画幅 × 三档
# 文件名要匹配门禁的 glob:封面_{mode}_*_{tier}.png
FORMATS = [
    # mode, 画幅名, tier, W, H, 布局
    ("916", "竖版", "标准", 1080, 1920, "tall"),
    ("916", "竖版", "高清", 2160, 3840, "tall"),
    ("916", "竖版", "小图", 480, 854, "tall"),
    ("34", "竖版", "标准", 1080, 1440, "tall"),
    ("34", "竖版", "高清", 2160, 2880, "tall"),
    ("34", "竖版", "小图", 480, 640, "tall"),
    ("43", "横版", "标准", 1440, 1080, "wide"),
    ("43", "横版", "高清", 2880, 2160, "wide"),
    ("43", "横版", "小图", 640, 480, "wide"),
    ("169", "横版", "标准", 1920, 1080, "wide"),
    ("169", "横版", "高清", 3840, 2160, "wide"),
    ("169", "横版", "小图", 854, 480, "wide"),
]


def scale_for(kind, W, H):
    """按画幅给一套尺寸参数(每个画幅自己排,不是同一版缩放)。"""
    base = W / 1080.0
    if kind == "tall":
        s = dict(L=60 * base, R=60 * base, T=64 * base, HT=190 * base, HH=430 * base,
                 TT=700 * base, TS=74 * base, RW=260 * base, RM=22 * base, CM=18 * base,
                 HR=20 * base, EBS=22 * base, DOT=9 * base, CS=20 * base,
                 SS=22 * base, SPT=24 * base, B=150 * base, BB=96 * base,
                 BAP=8 * base, BHP=18 * base, BFS=22 * base)
        # 3:4 比 9:16 矮,主视觉和标题整体上移
        if H / W < 1.5:
            s["HT"] = 150 * base
            s["HH"] = 340 * base
            s["TT"] = 560 * base
            s["TS"] = 66 * base
        return s
    s = dict(L=80 * base, R=80 * base, T=64 * base, TT=250 * base, TS=62 * base,
             TW=760 * base, RW=240 * base, RM=20 * base, CM=16 * base,
             HL=920 * base, HT=150 * base, HW=1040 * base, HH=620 * base,
             HR=18 * base, EBS=22 * base, DOT=9 * base, CS=20 * base,
             SS=22 * base, SPT=24 * base, B=110 * base, BB=96 * base,
             BAP=8 * base, BHP=18 * base, BFS=22 * base)
    # 4:3 比 16:9 矮,右栏往下压一点、左栏字大一点
    if H / W < 1.0:
        s["TT"] = 200 * base
        s["TS"] = 54 * base
        s["HL"] = 760 * base
        s["HW"] = 840 * base
        s["HH"] = 560 * base
        s["TW"] = 620 * base
    return s


def main():
    mp4 = os.path.join(ROOT, "成品", "shadow-ebook-promo-9x16.mp4")
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", mp4],
                         capture_output=True, text=True).stdout.strip()
    total = float(dur)
    badge = f"{int(total) // 60:02d}:{round(total) % 60:02d}"
    print(f"时长角标用 ffprobe 实测值: {total:.3f}s → {badge}")

    port = 9700
    proc = launch(port=port, profile="/tmp/chrome-covers", width=1080, height=1920)
    try:
        tab = new_tab(port=port, url="about:blank")
        cdp = CDP(tab["webSocketDebuggerUrl"])
        cdp.call("Runtime.enable")
        cdp.call("Page.enable")
        for mode, shape, tier, W, H, kind in FORMATS:
            s = scale_for(kind, W, H)
            css = CSS
            for k, val in s.items():
                css = css.replace(f"__{k}__", str(val))
            body = (layout_tall if kind == "tall" else layout_wide)(W, H, s)
            html = (f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style>"
                    f"</head><body><div class='cover' style='width:{W}px;height:{H}px'>"
                    f"{body}"
                    f"<div class='sign'><span>{SIGN}</span></div>"
                    f"<div class='badge'>{badge}</div>"
                    f"</div></body></html>")
            path = f"/tmp/cover-{mode}-{tier}.html"
            open(path, "w").write(html)
            cdp.call("Emulation.setDeviceMetricsOverride", {
                "width": W, "height": H, "deviceScaleFactor": 1, "mobile": False})
            cdp.call("Page.navigate", {"url": "file://" + path})
            time.sleep(1.2)
            shot = cdp.call("Page.captureScreenshot", {"format": "png"})
            out = f"{OUT}/封面_{mode}_{shape}_{tier}.png"
            with open(out, "wb") as f:
                f.write(base64.b64decode(shot["data"]))
            print(f"  ✓ {os.path.basename(out)}  {W}x{H}")
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
