#!/usr/bin/env python3
"""生成带中文旁白(TTS)和字幕的宣传视频。

流程:
  1. 六个场景各一段旁白 → edge-tts 合成 mp3 + srt(带时间轴)
  2. 场景时长由**音频实际长度**决定(不是拍脑袋写死的)
  3. HTML 分镜页按时间轴逐帧渲染(字幕跟着 srt 走,念到哪句亮哪句)
  4. ffmpeg 合成:画面 + 旁白
"""
import base64
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import CDP, launch, new_tab  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PADDED = "/tmp/promo/padded"
SHOTS = _PADDED if os.path.isdir(_PADDED) else os.path.join(ROOT, "promo", "padded")
VO = "/tmp/shadow-promo-vo"
FRAMES = "/tmp/shadow-promo-frames-vo"
OUT = f"{ROOT}/promo/video"
VENV = os.path.join(ROOT, "venv", "bin")
os.makedirs(VO, exist_ok=True)
os.makedirs(FRAMES, exist_ok=True)
os.makedirs(OUT, exist_ok=True)

FPS = 30
VOICE = "zh-CN-XiaoxiaoNeural"
RATE = "+12%"

# 每个场景:旁白 + 画面标题 + 副标题 + 图
SEGMENTS = [
    dict(key="s1", vo="这是我自己做的英语阅读器,叫影子电子书。一台电脑,家里平板就能用。",
         kicker="影子电子书", title="影子电子书", sub="局域网里的家庭英语阅读器",
         shot="shelf.png", fit="cover"),
    dict(key="s2", vo="读起来是纸的排版,点单词查释义,上一句下一句,一句一句地走。",
         kicker="阅读器", title="像书一样读", sub="点单词查释义 · 逐句朗读 · 读完自动接下一句",
         shot="reader.png", fit="cover"),
    dict(key="s3", vo="跟读这块花时间最多。它不说你这个词错了,直接说这个 o 的音还不稳,长 o 像 go。",
         kicker="跟读评分", title="读错了,告诉你是\n哪个「音」不对", sub="不是「这个词读错了」,是「/AO/ 还不稳」",
         shot="tutor-feedback-card.png", fit="contain"),
    dict(key="s4", vo="知识图谱把教材、考纲和掌握度画在一张图上。这一章要会什么,一眼看到。",
         kicker="知识图谱", title="教到哪、考到哪、\n孩子会哪", sub="教材单元 → 前置知识点 → 考纲对照",
         shot="tutor-mth.png", fit="cover"),
    dict(key="s5", vo="家长页是诊断,不是报表。哪个音不稳、哪个知识点没学会,直接列出来。",
         kicker="家长页", title="家长看到的是诊断,\n不是报表", sub="哪个音还不稳 · 哪个知识点没学会",
         shot="parent-panel.png", fit="cover"),
    dict(key="s6", vo="不用云端,书和孩子的录音都在自己家里。代码开源了,GitHub 上能找到。",
         kicker="结尾", title="一台电脑,全家平板", sub="不用注册 · 不用云端 · 数据留在家里",
         shot="shelf.png", fit="cover"),
]


def synth(seg):
    """合成一段旁白,返回 (时长秒, 字幕 cue 列表)。"""
    mp3 = f"{VO}/{seg['key']}.mp3"
    srt = f"{VO}/{seg['key']}.srt"
    if not (os.path.exists(mp3) and os.path.exists(srt)):
        subprocess.run([f"{VENV}/edge-tts", "--voice", VOICE, f"--rate={RATE}",
                        "--text", seg["vo"], "--write-media", mp3, "--write-subtitles", srt],
                       check=True, capture_output=True)
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", mp3], capture_output=True, text=True).stdout.strip())
    cues = parse_srt(open(srt, encoding="utf-8").read())
    return dur, cues


SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def parse_srt(text):
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        m = SRT_TIME.search(block)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        st = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        en = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        body = block[m.end():].strip().replace("\n", "")
        if body:
            out.append({"start": st, "end": en, "text": body})
    return out


def build_timeline():
    tl = []
    t = 0.0
    for seg in SEGMENTS:
        dur, cues = synth(seg)
        seg["dur"] = dur
        seg["cues"] = [{"start": c["start"], "end": c["end"], "text": c["text"]} for c in cues]
        tl.append(dict(t0=t, t1=t + dur, seg=seg))
        t += dur
    return tl, t


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
  padding-top:22px;border-top:1px solid rgba(45,42,38,.09);
  display:flex;align-items:center;justify-content:space-between;
  font-size:__FS__px;color:#5A544C;white-space:nowrap;
}
.foot b{font-family:'SF Mono',Menlo,Consolas,monospace;font-weight:400;color:#B86A4E;
  font-size:calc(__FS__px * .86);white-space:nowrap;}
/* 字幕条:底部一块半透明纸,当前念到的那句亮起来 */
.subs{
  position:absolute;left:__PX__px;right:__PX__px;bottom:__SUBB__px;
  display:flex;justify-content:center;
  /* 必须压在场景之上:字幕条在 DOM 里排在场景**前面**
     (stage 的 HTML 里先有 bar/subs,场景是 JS 追加的),
     而横版右栏那一格有不透明底色,不加 z-index 就把字幕盖住了。 */
  z-index:5;
}
.subs-inner{
  max-width:__SUBW__px;text-align:center;
  background:rgba(252,251,248,.82);
  border:1px solid rgba(45,42,38,.10);
  border-radius:14px;
  padding:16px 30px;
  font-size:__SUBS__px;line-height:1.6;color:#5A544C;font-weight:400;
  backdrop-filter:blur(10px);
  box-shadow:0 10px 30px rgba(45,42,38,.10);
}
.subs-inner .on{color:#B86A4E;font-weight:600;}
.bar{position:absolute;left:0;top:0;height:5px;background:#B86A4E;width:0;}

/* —— 横版:左文右图 —— */
.land .scene{display:grid;grid-template-columns:42% 58%;padding:0;}
/* 网格项默认 min-width:auto,会被图片的固有宽度撑开、盖到文字上 */
.land .scene>*{min-width:0;}
.land .txt{padding:76px 60px 190px 96px;display:flex;flex-direction:column;justify-content:center;}
.land .txt h1{font-size:62px;}
.land .txt .sub{font-size:24px;margin-top:18px;}
.land .side{position:relative;overflow:hidden;background:#FCFBF8;
  border-left:1px solid rgba(45,42,38,.10);}
.land .side .inner{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;}
.land .side .inner img{width:92%;aspect-ratio:8/5;object-fit:cover;object-position:center top;
  border-radius:16px;box-shadow:0 20px 50px rgba(45,42,38,.16);}
.land .side .inner img.contain{object-fit:contain;}
.land .foot{left:96px;right:60px;bottom:150px;}
.land .subs{left:0;right:0;bottom:24px;}
.land .subs-inner{max-width:1180px;}
"""

HTML = """<!doctype html><html><head><meta charset="utf-8"><style>__CSS__</style></head>
<body><div class="stage" id="stage"><div class="bar" id="bar"></div></div>
<script>
const SCENES = __SCENES__;
const TOTAL = __TOTAL__;
const stage = document.getElementById('stage');
const LAND = __LAND__;
const els = SCENES.map(s => {
  const d = document.createElement('div');
  d.className = 'scene';
  const kicker = '<div class="kicker"><i></i><s></s><span>' + s.kicker + '</span></div>';
  const h1 = '<h1>' + s.title + '</h1>';
  const sub = '<div class="sub">' + s.sub + '</div>';
  const foot = '<div class="foot"><span>一台电脑服务全家平板</span>' +
               '<b>github.com/Joshhuang123/shadow-ebook</b></div>';
  if (LAND) {
    d.innerHTML = '<div class="txt">' + kicker + h1 + sub + foot + '</div>' +
                  '<div class="side"><div class="inner">' +
                  '<img class="' + s.fit + '" src="' + s.img + '"></div></div>';
  } else {
    d.innerHTML = kicker + h1 +
      '<div class="shot ' + s.fit + '"><img src="' + s.img + '"></div>' +
      sub + foot;
  }
  stage.appendChild(d);
  return d;
});
function showFrame(t) {
  document.getElementById('bar').style.width = (t / TOTAL * 100) + '%';
  let active = -1;
  for (let i = 0; i < SCENES.length; i++) {
    const s = SCENES[i];
    const on = t >= s.t0 && t < s.t1;
    els[i].classList.toggle('on', on);
    if (!on) { els[i].style.opacity = '0'; els[i].style.transform = 'none'; continue; }
    active = i;
    const k = (t - s.t0) / (s.t1 - s.t0);
    const e = Math.min(1, k / 0.12);
    const ease = 1 - Math.pow(1 - e, 3);
    els[i].style.transform = 'translateY(' + ((1 - ease) * 34).toFixed(2) + 'px)';
    els[i].style.opacity = ease.toFixed(3);
    const img = els[i].querySelector('img');
    if (img) img.style.transform = 'scale(' + (1.0 + 0.05 * k).toFixed(4) + ')';
  }
  // 字幕:当前场景的那一句,念到哪句哪句亮
  if (active >= 0) {
    const s = SCENES[active];
    const local = t - s.t0;
    let html = '';
    for (const c of s.cues) {
      const on = local >= c.start && local < c.end;
      html += '<span class="' + (on ? 'on' : '') + '">' + c.text + '</span>';
    }
    const band = document.getElementById('subs');
    band.innerHTML = '<div class="subs-inner">' + html + '</div>';
  } else {
    document.getElementById('subs').innerHTML = '';
  }
}
showFrame(0);
</script></body></html>"""


def img(name):
    p = os.path.join(SHOTS, name)
    return "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()


VARIANTS = {
    # FB(页脚下沿) 和 SUBB(字幕条下沿) 要错开,不然两层会叠在一起
    "9x16": dict(land=False, W=1080, H=1920, PT=150, PX=76, PB=330, KM=34, KS=25, TS=88, TM=28,
                 SM=48, SS=30, SBM=36, SW=928, SH=580, FS=25, FB=250, SUBB=70,
                 SUBS=34, SUBW=900),
    "16x9": dict(land=True, W=1600, H=900, PT=70, PX=60, PB=210, KM=26, KS=20, TS=62, TM=20,
                 SM=30, SS=24, SBM=18, SW=560, SH=350, FS=20, FB=150, SUBB=24,
                 SUBS=26, SUBW=1180),
}


def render(variant, tl, total):
    v = VARIANTS[variant]
    W, H = v["W"], v["H"]
    css = CSS
    for k, val in v.items():
        css = css.replace(f"__{k}__", str(val))
    scenes = []
    for item in tl:
        s = item["seg"]
        scenes.append(dict(t0=item["t0"], t1=item["t1"], kicker=s["kicker"],
                            title=s["title"], sub=s["sub"], img=img(s["shot"]),
                            fit=s["fit"], cues=s["cues"]))
    html = (HTML.replace("__CSS__", css)
                .replace("__SCENES__", json.dumps(scenes, ensure_ascii=False))
                .replace("__TOTAL__", str(total))
                .replace("__LAND__", "true" if v["land"] else "false"))
    # 字幕条容器
    html = html.replace('<div class="bar" id="bar"></div>',
                        '<div class="bar" id="bar"></div><div class="subs" id="subs"></div>')
    if v["land"]:
        html = html.replace('class="stage"', 'class="stage land"')
    path = f"/tmp/shadow-promo-story-{variant}.html"
    open(path, "w").write(html)

    nframes = int(total * FPS) + 2
    port = 9670 if variant == "9x16" else 9671
    proc = launch(port=port, profile=f"/tmp/chrome-vo-{variant}", width=W, height=H)
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
        for i in range(nframes):
            cdp.call("Runtime.evaluate", {"expression": f"showFrame({i / FPS:.4f})"})
            s = cdp.call("Page.captureScreenshot", {"format": "png"})
            with open(f"{FRAMES}/f{i:05d}.png", "wb") as f:
                f.write(base64.b64decode(s["data"]))
            if i % 90 == 0:
                print(f"  [{variant}] {i}/{nframes}  {time.time()-t0:.0f}s", flush=True)
    finally:
        proc.terminate()
    print(f"[{variant}] 渲染 {nframes} 帧,{time.time()-t0:.0f}s", flush=True)

    # 旁白拼成一条
    lst = f"{VO}/list-{variant}.txt"
    with open(lst, "w") as f:
        for item in tl:
            f.write(f"file '{VO}/{item['seg']['key']}.mp3'\n")
    voice = f"{VO}/voice-{variant}.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", lst, "-c", "copy", voice], check=True)

    out_mp4 = f"{OUT}/shadow-ebook-promo-{variant}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                    "-i", f"{FRAMES}/f%05d.png", "-i", voice,
                    "-c:v", "libx264", "-preset", "slow", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                    "-shortest", "-movflags", "+faststart", out_mp4], check=True)
    print("成片:", out_mp4, flush=True)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "9x16"
    tl, total = build_timeline()
    print(f"旁白 {len(tl)} 段,总时长 {total:.1f}s", flush=True)
    for item in tl:
        print(f"  {item['seg']['key']} {item['t0']:.1f}-{item['t1']:.1f}s "
              f"({item['seg']['dur']:.1f}s) {item['seg']['cues'][0]['text'][:24]}…", flush=True)
    render(which, tl, total)
