#!/usr/bin/env python3
"""封面投放包:四画幅 × 三档 = 12 张。

照 josh-media skill 的封面铁律:
  1. **四画幅各自排版**,不是同一版裁切或拉伸 —— 每个画幅一套几何
     (竖版堆叠、横版并置),各画幅内容填充率接近,不许空一大半。
  2. 真实感靠原件:主视觉是**真截图**,旁边标出处。
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

HERO = "tutor-feedback-card.png"     # 主视觉:真截图(跟读那张最有说服力)
CREDIT = "真实运行截图 · 影子电子书"
TITLE = "孩子读错哪个「音」\n它能指出来"
LEAD = "别的软件只说你这个词读错了。\n它直接说:这个 o 的音还不稳,长 o 像 go。"
EYEBROW = "影子电子书 · 局域网里的家庭英语阅读器"
SIGN = "一台电脑服务全家平板 · 数据留在家里"

CSS = """
*{margin:0;padding:0;box-sizing:border-box;}
body{background:#F4F1EA;}
.cover{
  position:relative;overflow:hidden;
  background:
    radial-gradient(1100px 620px at 84% -6%, rgba(212,165,116,.13) 0%, transparent 62%),
    radial-gradient(820px 560px at 4% 102%, rgba(122,139,159,.07) 0%, transparent 60%),
    linear-gradient(160deg,#F8F5EF 0%,#EDE6D9 100%);
  font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Helvetica Neue','Segoe UI',Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;color:#2D2A26;
}
.eyebrow{position:absolute;left:__L__px;top:__T__px;
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
.hero img{width:100%;height:100%;object-fit:contain;object-position:center top;display:block;}
.credit{font-size:__CS__px;color:#8A857C;letter-spacing:.02em;}
.lead{font-size:__LS__px;line-height:1.6;color:#5A544C;font-weight:300;white-space:pre-line;}
.sign{position:absolute;left:__L__px;bottom:__B__px;right:__R__px;
  padding-top:__SPT__px;border-top:1px solid rgba(45,42,38,.12);
  display:flex;align-items:center;justify-content:space-between;gap:16px;
  font-size:__SS__px;color:#5A544C;}
.badge{position:absolute;right:__R__px;bottom:__BB__px;
  padding:__BAP__px __BHP__px;border-radius:9999px;
  background:rgba(45,42,38,.9);color:#FCFBF8;font-size:__BFS__px;
  font-family:'SF Mono',Menlo,Consolas,monospace;letter-spacing:.02em;}
"""


def img(name):
    p = os.path.join(SHOTS, name)
    if not os.path.exists(p):
        return ""
    return "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()


# ── 竖版:眉标 → 主视觉 → 标题 → 出处 → 一句话 → 部署名 → 角标 ──
def layout_tall(g):
    return f"""
    <div class="eyebrow"><i></i><span>{EYEBROW}</span></div>
    <div class="hero" style="position:absolute;left:{g['L']}px;right:{g['R']}px;
         top:{g['HT']}px;height:{g['HH']}px"><img src="{img(HERO)}"></div>
    <div style="position:absolute;left:{g['L']}px;right:{g['R']}px;top:{g['TT']}px">
      <div class="title" style="font-size:{g['TS']}px">{TITLE}</div>
      <div class="rule" style="width:{g['RW']}px;margin-top:{g['RM']}px"></div>
      <div class="credit" style="margin-top:{g['CM']}px">{CREDIT}</div>
      <div class="lead" style="margin-top:{g['LM']}px">{LEAD}</div>
    </div>"""


# ── 横版:眉标左上 → 文字左 → 主视觉右 → 部署名 → 角标右下 ──
def layout_wide(g):
    return f"""
    <div class="eyebrow"><i></i><span>{EYEBROW}</span></div>
    <div style="position:absolute;left:{g['L']}px;top:{g['TT']}px;width:{g['TW']}px">
      <div class="title" style="font-size:{g['TS']}px">{TITLE}</div>
      <div class="rule" style="width:{g['RW']}px;margin-top:{g['RM']}px"></div>
      <div class="credit" style="margin-top:{g['CM']}px">{CREDIT}</div>
      <div class="lead" style="margin-top:{g['LM']}px">{LEAD}</div>
    </div>
    <div class="hero" style="position:absolute;left:{g['HL']}px;top:{g['HT']}px;
         width:{g['HW']}px;height:{g['HH']}px"><img src="{img(HERO)}"></div>"""


# 四个画幅各自一套几何(不是同一版缩放)
GEOM = {
    "916": dict(L=68, R=68, T=90, HT=200, HH=700, TT=980, TS=76, RW=270, RM=22, CM=16,
                LM=34, LS=27, EBS=23, DOT=9, CS=19, SS=21, SPT=24, B=150, BB=96,
                BAP=8, BHP=18, BFS=21, HR=20, mode="tall"),
    "34": dict(L=64, R=64, T=70, HT=160, HH=540, TT=790, TS=70, RW=250, RM=20, CM=14,
               LM=28, LS=25, EBS=21, DOT=8, CS=18, SS=20, SPT=22, B=120, BB=78,
               BAP=7, BHP=16, BFS=19, HR=18, mode="tall"),
    "43": dict(L=80, R=80, T=80, TT=250, TS=60, TW=640, RW=220, RM=18, CM=14, LM=26,
               LS=23, EBS=21, DOT=8, CS=18, SS=20, SPT=22, B=120, BB=78,
               BAP=7, BHP=16, BFS=19, HR=18, HL=800, HT=200, HW=560, HH=520,
               mode="wide"),
    "169": dict(L=100, R=100, T=90, TT=270, TS=66, TW=760, RW=250, RM=20, CM=16, LM=30,
                LS=25, EBS=24, DOT=9, CS=20, SS=22, SPT=26, B=110, BB=80,
                BAP=8, BHP=18, BFS=21, HR=20, HL=960, HT=190, HW=860, HH=620,
                mode="wide"),
}

TIERS = {"标准": 1, "高清": 2, "小图": 0.45}


def main():
    mp4 = os.path.join(ROOT, "成品", "shadow-ebook-promo-9x16.mp4")
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "default=nw=1:nk=1", mp4],
                               capture_output=True, text=True).stdout.strip())
    badge = f"{int(dur) // 60:02d}:{round(dur) % 60:02d}"
    print(f"时长角标用 ffprobe 实测值: {dur:.3f}s → {badge}")

    port = 9700
    proc = launch(port=port, profile="/tmp/chrome-covers2", width=1080, height=1920)
    try:
        tab = new_tab(port=port, url="about:blank")
        cdp = CDP(tab["webSocketDebuggerUrl"])
        cdp.call("Runtime.enable")
        cdp.call("Page.enable")
        for mode, base in GEOM.items():
            for tier, k in TIERS.items():
                g = {key: (round(val * k) if isinstance(val, (int, float)) else val)
                     for key, val in base.items()}
                css = CSS
                for key, val in g.items():
                    css = css.replace(f"__{key}__", str(val))
                body = (layout_tall if g["mode"] == "tall" else layout_wide)(g)
                W, H = (1080, 1920) if mode == "916" else (1080, 1440) if mode == "34" else \
                      (1440, 1080) if mode == "43" else (1920, 1080)
                W, H = int(W * k), int(H * k)
                html = (f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style>"
                        f"</head><body><div class='cover' style='width:{W}px;height:{H}px'>"
                        f"{body}"
                        f"<div class='sign'><span>{SIGN}</span></div>"
                        f"<div class='badge'>{badge}</div>"
                        f"</div></body></html>")
                path = f"/tmp/cover2-{mode}-{tier}.html"
                open(path, "w").write(html)
                cdp.call("Emulation.setDeviceMetricsOverride", {
                    "width": W, "height": H, "deviceScaleFactor": 1, "mobile": False})
                cdp.call("Page.navigate", {"url": "file://" + path})
                time.sleep(1.1)
                shot = cdp.call("Page.captureScreenshot", {"format": "png"})
                shape = "竖版" if g["mode"] == "tall" else "横版"
                out = f"{OUT}/封面_{mode}_{shape}_{tier}.png"
                with open(out, "wb") as f:
                    f.write(base64.b64decode(shot["data"]))
                print(f"  ✓ {os.path.basename(out)}  {W}x{H}")
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
