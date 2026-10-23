#!/usr/bin/env python3
"""生成宣传短视频(9:16 竖版 + 16:9 横版)。

做法:一个 HTML 分镜页,JS 按时间 t 决定每一帧显示什么、位移多少;
CDP 逐帧截图 → ffmpeg 合成 mp4。素材是真实界面 + 项目自己的字体。
"""
import base64
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import CDP, launch, new_tab  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "padded")
FRAMES = "/tmp/shadow-promo-frames"
OUT = os.path.join(ROOT, "video")
os.makedirs(FRAMES, exist_ok=True)
os.makedirs(OUT, exist_ok=True)

FPS = 30
DURATION = 24.0
TOTAL = int(DURATION * FPS)

# (起, 止, 小标签, 主标题, 副标题, 图, 图的适配)
SCENES = [
    (0.0, 4.0, "影子电子书", "影子电子书",
     "局域网里的家庭英语阅读器", "shelf.png", "cover"),
    (4.0, 7.5, "阅读器", "像书一样读",
     "点单词查释义 · 逐句朗读 · 读完自动接下一句", "reader.png", "cover"),
    (7.5, 11.0, "跟读评分", "读错了,告诉你是\n哪个「音」不对",
     "不是「这个词读错了」,是「/AO/ 还不稳」", "tutor-feedback-card.png", "contain"),
    (11.0, 15.0, "知识图谱", "教到哪、考到哪、\n孩子会哪",
     "教材单元 → 前置知识点 → 考纲对照", "tutor-mth.png", "cover"),
    (15.0, 19.0, "家长页", "家长看到的是诊断,\n不是报表",
     "哪个音还不稳 · 哪个知识点没学会", "parent-panel.png", "cover"),
    (19.0, 24.0, "结尾", "一台电脑,全家平板",
     "不用注册 · 不用云端 · 数据留在家里", "shelf.png", "cover"),
]

CSS = """
*{margin:0;padding:0;box-sizing:border-box;}
html,body{width:__W__px;height:__H__px;overflow:hidden;background:#F4F1EA;}
.stage{
  position:relative;width:__W__px;height:__H__px;overflow:hidden;
  background:
    radial-gradient(900px 520px at 82% -6%, rgba(212,165,116,.13) 0%, transparent 62%),
    radial-gradient(700px 480px at 4% 102%, rgba(122,139,159,.08) 0%, transparent 60%),
    linear-gradient(160deg,#F8F5EF 0%,#EDE6D9 100%);
  font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Helvetica Neue','Segoe UI',Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;
}
.scene{position:absolute;inset:0;opacity:0;display:flex;flex-direction:column;
  padding:__PT__px __PX__px __PB__px;}
.kicker{
  display:inline-flex;align-items:center;gap:12px;
  font-size:__KS__px;font-weight:600;letter-spacing:.24em;color:#B86A4E;margin-bottom:__KM__px;
}
.kicker i{width:9px;height:9px;border-radius:50%;background:#B86A4E;display:block;}
.kicker s{display:block;width:52px;height:1px;background:rgba(45,42,38,.16);text-decoration:none;}
h1{
  font-family:'Iowan Old Style','Palatino',Georgia,'Songti SC Black','STSongti-SC-Black',
              'Songti SC','STSong','SimSun','Source Han Serif SC','Noto Serif CJK SC',serif;
  font-weight:700;font-size:__TS__px;line-height:1.16;letter-spacing:-.015em;color:#2D2A26;
  white-space:pre-line;margin-bottom:__TM__px;
}
.shot{
  position:relative;margin-top:__SM__px;border-radius:20px;overflow:hidden;
  background:#FCFBF8;border:1px solid rgba(45,42,38,.14);
  box-shadow:0 26px 60px rgba(45,42,38,.15),0 3px 8px rgba(45,42,38,.07);
  width:__SW__px;height:__SH__px;
}
.shot img{width:100%;height:100%;object-fit:cover;object-position:center top;display:block;}
.shot.contain img{object-fit:contain;}
.sub{font-size:__SS__px;line-height:1.7;color:#5A544C;font-weight:300;white-space:pre-line;
  margin-top:__SBM__px;}
.foot{
  position:absolute;left:__PX__px;right:__PX__px;bottom:__FB__px;
  padding-top:26px;border-top:1px solid rgba(45,42,38,.09);
  display:flex;align-items:center;justify-content:space-between;
  font-size:__FS__px;color:#5A544C;white-space:nowrap;
}
.foot b{font-family:'SF Mono',Menlo,Consolas,monospace;font-weight:400;color:#B86A4E;
  font-size:calc(__FS__px * .86);white-space:nowrap;}
.bar{position:absolute;left:0;top:0;height:5px;background:#B86A4E;width:0;}

/* —— 横版:文字左,画面右 —— */
.land .scene{display:grid;grid-template-columns:44% 56%;padding:0;}
/* 网格项默认 min-width:auto,会被图片的固有宽度撑开、盖到文字上 */
.land .scene>*{min-width:0;}
.land .txt{padding:__PT__px __PX2__px __PB__px 96px;display:flex;flex-direction:column;justify-content:center;}
.land .txt .shot{margin-top:__SM__px;}
.land .side{position:relative;overflow:hidden;background:#FCFBF8;
  border-left:1px solid rgba(45,42,38,.10);}
.land .side img{width:100%;height:100%;object-fit:cover;object-position:center top;display:block;}
.land .side .inner{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;}
.land .side .inner img{
  /* 定框 + object-fit:只靠 max-width/max-height 会把图拉变形
     (宽高比不保),字会糊。 */
  width:92%;aspect-ratio:8/5;object-fit:cover;object-position:center top;
  border-radius:16px;box-shadow:0 20px 50px rgba(45,42,38,.16);
}
.land .side .inner img.contain{object-fit:contain;}
.land .foot{left:96px;right:__PX2__px;}
"""

HTML = """<!doctype html><html><head><meta charset="utf-8"><style>__CSS__</style></head>
<body><div class="stage __LANDCLASS__" id="stage"><div class="bar" id="bar"></div></div>
<script>
const SCENES = __SCENES__;
const DURATION = __DURATION__;
const LAND = __LAND__;
const stage = document.getElementById('stage');
const els = SCENES.map(s => {
  const d = document.createElement('div');
  d.className = 'scene';
  const kicker = '<div class="kicker"><i></i><s></s><span>' + s.kicker + '</span></div>';
  const h1 = '<h1>' + s.title + '</h1>';
  const foot = '<div class="foot"><span>一台电脑服务全家平板</span>' +
               '<b>github.com/Joshhuang123/shadow-ebook</b></div>';
  if (LAND) {
    const side = s.img
      ? '<div class="side"><div class="inner"><img class="' + s.fit + '" src="' + s.img + '"></div></div>'
      : '<div class="side"></div>';
    d.innerHTML = '<div class="txt">' + kicker + h1 +
                  '<div class="sub">' + s.sub + '</div>' + foot + '</div>' + side;
  } else {
    const shot = s.img
      ? '<div class="shot ' + s.fit + '"><img src="' + s.img + '"></div>' : '';
    d.innerHTML = kicker + h1 + shot + '<div class="sub">' + s.sub + '</div>' + foot;
  }
  stage.appendChild(d);
  return d;
});
function showFrame(t) {
  document.getElementById('bar').style.width = (t / DURATION * 100) + '%';
  for (let i = 0; i < SCENES.length; i++) {
    const s = SCENES[i];
    const on = t >= s.t0 && t < s.t1;
    els[i].classList.toggle('on', on);
    if (!on) {
      // 必须显式清零:上一帧设过的内联 opacity 留着,所有场景会叠在一起
      els[i].style.opacity = '0';
      els[i].style.transform = 'none';
      continue;
    }
    const k = (t - s.t0) / (s.t1 - s.t0);
    const e = Math.min(1, k / 0.18);
    const ease = 1 - Math.pow(1 - e, 3);
    els[i].style.transform = 'translateY(' + ((1 - ease) * 40).toFixed(2) + 'px)';
    els[i].style.opacity = ease.toFixed(3);
    const img = els[i].querySelector('img');
    if (img) img.style.transform = 'scale(' + (1.0 + 0.06 * k).toFixed(4) + ')';
  }
}
showFrame(0);
</script></body></html>"""


def img(name):
    if not name:
        return ""
    p = os.path.join(SHOTS, name)
    if not os.path.exists(p):
        return ""
    return "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()


# 竖版 / 横版两套尺寸
VARIANTS = {
    "9x16": dict(W=1080, H=1920, land=False, PT=170, PX=76, PB=210, KM=38, KS=25,
                 TS=92, TM=30, SM=54, SS=32, SBM=40, SW=928, SH=580, FS=25,
                 FB=110, PX2=76),
    "16x9": dict(W=1600, H=900, land=True, PT=90, PX=60, PB=90, KM=30, KS=21,
                 TS=68, TM=22, SM=36, SS=26, SBM=20, SW=560, SH=350, FS=21,
                 FB=70, PX2=60),
}


def build_html(v):
    import json as _json
    scenes = []
    for t0, t1, kicker, title, sub, shot, fit in SCENES:
        scenes.append({"t0": t0, "t1": t1, "kicker": kicker, "title": title,
                        "sub": sub, "img": img(shot), "fit": fit})
    css = CSS
    for k, val in v.items():
        css = css.replace(f"__{k}__", str(val))
    return (HTML.replace("__CSS__", css)
                .replace("__SCENES__", _json.dumps(scenes, ensure_ascii=False))
                .replace("__DURATION__", str(DURATION))
                .replace("__LAND__", "true" if v["land"] else "false")
                .replace("__LANDCLASS__", "land" if v["land"] else ""))


def render(variant):
    v = VARIANTS[variant]
    W, H = v["W"], v["H"]
    frames_dir = f"/tmp/shadow-promo-frames-{variant}"
    os.makedirs(frames_dir, exist_ok=True)
    path = f"/tmp/shadow-promo-story-{variant}.html"
    open(path, "w").write(build_html(v))
    port = 9620 if variant == "9x16" else 9621
    proc = launch(port=port, profile=f"/tmp/chrome-video-{variant}", width=W, height=H)
    t0 = time.time()
    try:
        tab = new_tab(port=port, url="file://" + path)
        cdp = CDP(tab["webSocketDebuggerUrl"])
        cdp.call("Runtime.enable")
        cdp.call("Page.enable")
        cdp.call("Emulation.setDeviceMetricsOverride", {
            "width": W, "height": H, "deviceScaleFactor": 1, "mobile": False})
        cdp.call("Page.navigate", {"url": "file://" + path})
        time.sleep(2.0)
        for i in range(TOTAL):
            cdp.call("Runtime.evaluate", {"expression": f"showFrame({i / FPS:.4f})"})
            s = cdp.call("Page.captureScreenshot", {"format": "png"})
            with open(f"{frames_dir}/f{i:05d}.png", "wb") as f:
                f.write(base64.b64decode(s["data"]))
            if i % 120 == 0:
                el = time.time() - t0
                print(f"  [{variant}] 帧 {i}/{TOTAL}  已用 {el:.0f}s", flush=True)
    finally:
        proc.terminate()
    print(f"[{variant}] 渲染完成:{TOTAL} 帧,耗时 {time.time()-t0:.0f}s", flush=True)

    out_mp4 = f"{OUT}/shadow-ebook-promo-{variant}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                    "-i", f"{frames_dir}/f%05d.png",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_mp4], check=True)
    print("成片:", out_mp4, flush=True)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "9x16"
    render(which)
