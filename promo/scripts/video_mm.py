#!/usr/bin/env python3
"""用 MiniMax 沉稳高管旁白渲染宣传视频(竖版 / 横版)。

时间轴来自 tts_minimax.py 产出的 timeline.json(逐句真实音频时长),
字幕跟着句子的 start/end 走 —— 换音色重合成,画面自己跟上。

纪律(josh-media skill):
  · 音色锁死沉稳高管,全系列一个
  · 响度归一到 -16 LUFS
  · 句间静音 0.30s、场间 0.75s、片尾 2.75s(在 timeline 里)
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
TL_JSON = "/tmp/promo_minimax/timeline.json"
FRAMES = "/tmp/shadow-promo-frames-mm"
OUT = os.path.join(ROOT, "成品")
os.makedirs(FRAMES, exist_ok=True)
os.makedirs(OUT, exist_ok=True)

FPS = 30
LUFS = -16

# 场:小标签 / 标题 / 副标题 / 图
SCENES = [
    dict(scene=1, kicker="影子电子书", title="影子电子书",
         sub="局域网里的家庭英语阅读器", shot="shelf.png", fit="cover"),
    dict(scene=2, kicker="阅读器", title="像书一样读",
         sub="点单词查释义 · 逐句朗读 · 读完自动接下一句", shot="reader.png", fit="cover"),
    dict(scene=3, kicker="跟读评分", title="读错了,告诉你是\n哪个「音」不对",
         sub="不是「这个词读错了」,是「/AO/ 还不稳」",
         shot="tutor-feedback-card.png", fit="contain"),
    dict(scene=4, kicker="知识图谱", title="教到哪、考到哪、\n孩子会哪",
         sub="教材单元 → 前置知识点 → 考纲对照", shot="tutor-mth.png", fit="cover"),
    dict(scene=5, kicker="家长页", title="家长看到的是诊断,\n不是报表",
         sub="哪个音还不稳 · 哪个知识点没学会", shot="parent-panel.png", fit="cover"),
    dict(scene=6, kicker="结尾", title="一台电脑,全家平板",
         sub="不用注册 · 不用云端 · 数据留在家里", shot="shelf.png", fit="cover"),
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
  background:rgba(252,251,248,.86);
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
<body><div class="stage" id="stage"><div class="bar" id="bar"></div><div class="subs" id="subs"></div></div>
<script>
const SCENES = __SCENES__;
const LINES = __LINES__;
const TOTAL = __TOTAL__;
const LAND = __LAND__;
const stage = document.getElementById('stage');
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
      '<div class="shot ' + s.fit + '"><img src="' + s.img + '"></div>' + sub + foot;
  }
  stage.appendChild(d);
  return d;
});
function showFrame(t) {
  document.getElementById('bar').style.width = (t / TOTAL * 100) + '%';
  // 当前场:由句子的时间轴反推(句子带 scene 号)
  let scene = SCENES[0].scene;
  for (const l of LINES) { if (t >= l.start) scene = l.scene; else break; }
  const idx = SCENES.findIndex(s => s.scene === scene);
  for (let i = 0; i < SCENES.length; i++) {
    const on = i === idx;
    els[i].classList.toggle('on', on);
    if (!on) { els[i].style.opacity = '0'; els[i].style.transform = 'none'; continue; }
    const s = SCENES[i];
    const first = LINES.find(l => l.scene === s.scene);
    const last  = [...LINES].reverse().find(l => l.scene === s.scene);
    const k = Math.max(0, Math.min(1, (t - first.start) / Math.max(0.001, last.end - first.start)));
    const e = Math.min(1, k / 0.10);
    const ease = 1 - Math.pow(1 - e, 3);
    els[i].style.transform = 'translateY(' + ((1 - ease) * 34).toFixed(2) + 'px)';
    els[i].style.opacity = ease.toFixed(3);
    const img = els[i].querySelector('img');
    if (img) img.style.transform = 'scale(' + (1.0 + 0.05 * k).toFixed(4) + ')';
  }
  // 字幕:当前场里,念到哪句哪句亮
  const mine = LINES.filter(l => l.scene === scene);
  let html = '';
  for (const l of mine) {
    const on = t >= l.start && t < l.end;
    html += '<span class="' + (on ? 'on' : '') + '">' + l.text + '</span>';
  }
  document.getElementById('subs').innerHTML = '<div class="subs-inner">' + html + '</div>';
}
showFrame(0);
</script></body></html>"""


def img(name):
    p = os.path.join(SHOTS, name)
    return "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()


VARIANTS = {
    "9x16": dict(land=False, W=1080, H=1920, PT=150, PX=76, PB=330, KM=34, KS=25, TS=88, TM=28,
                 SM=48, SS=30, SBM=36, SW=928, SH=580, FS=25, FB=250, SUBB=70,
                 SUBS=34, SUBW=900),
    "16x9": dict(land=True, W=1600, H=900, PT=70, PX=60, PB=210, KM=26, KS=20, TS=62, TM=20,
                 SM=30, SS=24, SBM=18, SW=560, SH=350, FS=20, FB=150, SUBB=24,
                 SUBS=26, SUBW=1180),
}


def render(variant):
    v = VARIANTS[variant]
    W, H = v["W"], v["H"]
    tl = json.load(open(TL_JSON))
    lines = [dict(scene=l["scene"], text=l["text"], start=l["start"], end=l["end"],
                  mp3=l["mp3"]) for l in tl["lines"]]
    total = tl["total"]
    scenes = []
    for s in SCENES:
        scenes.append(dict(s, img=img(s["shot"])))
    css = CSS
    for k, val in v.items():
        css = css.replace(f"__{k}__", str(val))
    html = (HTML.replace("__CSS__", css)
                .replace("__SCENES__", json.dumps(scenes, ensure_ascii=False))
                .replace("__LINES__", json.dumps(lines, ensure_ascii=False))
                .replace("__TOTAL__", str(total))
                .replace("__LAND__", "true" if v["land"] else "false"))
    if v["land"]:
        html = html.replace('class="stage"', 'class="stage land"')
    path = f"/tmp/shadow-promo-mm-{variant}.html"
    open(path, "w").write(html)

    fdir = f"{FRAMES}-{variant}"          # 每个画幅一个帧目录
    os.makedirs(fdir, exist_ok=True)
    mux_only = "--mux-only" in sys.argv
    nframes = int(total * FPS) + 2
    port = 9690 if variant == "9x16" else 9691
    if mux_only:
        print(f"[{variant}] --mux-only:复用已渲好的帧", flush=True)
    else:
        _render_frames(variant, path, fdir, nframes, W, H, port, total)
    _mux(variant, lines, total, fdir)
    return


def _render_frames(variant, path, fdir, nframes, W, H, port, total):
    proc = launch(port=port, profile=f"/tmp/chrome-mm-{variant}", width=W, height=H)
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
            with open(f"{fdir}/f{i:05d}.png", "wb") as f:
                f.write(base64.b64decode(s["data"]))
            if i % 120 == 0:
                print(f"  [{variant}] {i}/{nframes}  {time.time()-t0:.0f}s", flush=True)
    finally:
        proc.terminate()
    print(f"[{variant}] 渲染 {nframes} 帧,{time.time()-t0:.0f}s", flush=True)


def _measure_loudness(path):
    """量一条音轨的 integrated loudness(I)和 true peak(TP)。

    注意:ebur128 会先打一堆逐帧进度行,里面的 I: 是「到目前为止」的累计值
    (开头会显示 -70 上下),只有最后 Summary 段才是全程实测值 ——
    必须只取 Summary,否则会读到开头的假值。
    """
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path,
         "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, check=True).stderr
    summary = out.split("Summary:")[-1]
    m_i = re.search(r"^\s*I:\s*(-?[\d.]+)\s*LUFS", summary, re.M)
    m_tp = re.search(r"^\s*Peak:\s*(-?[\d.]+)\s*dBFS", summary, re.M)
    if not (m_i and m_tp):
        raise RuntimeError(f"响度测量失败:\n{summary[-800:]}")
    return {"I": float(m_i.group(1)), "TP": float(m_tp.group(1))}


# 限制器上限 -1.5 dBFS(采样峰),留出真峰(inter-sample)余量
_LIMIT = 10 ** (-1.5 / 20)


def _normalize_voice(src, dst):
    """把旁白归一到 -16 LUFS、峰值不过 -1.5 dBTP。

    为什么不用 loudnorm 的动态模式:沉稳高管这版素材波峰因子约 20 dB,
    loudnorm 内置限制器会把 integrated loudness 压低 1.1 LU(实测落在 -17.1),
    固定 +3.1dB 更糟 —— 直接顶到 +1.7dBTP(削波)。
    这里改成「线性增益 + 透明砖墙限制器」,再按实测误差迭代增益:
    限制器只削最响的几个峰,integrated 不会被拖下来。
    """
    gain = 0.0
    stats = None
    for _ in range(6):
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", src,
             "-af", (f"volume={gain:.2f}dB,"
                     f"alimiter=limit={_LIMIT:.4f}:level=disabled:"
                     f"attack=5:release=50:latency=1"),
             "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", dst], check=True)
        stats = _measure_loudness(dst)
        err = LUFS - stats["I"]
        if abs(err) <= 0.1 and stats["TP"] <= -1.0:
            break
        gain += err
    return stats, gain


def _mux(variant, lines, total, fdir):
    # 旁白拼成一条(句间静音已经在 timeline 里算进 start/end 了,
    # 所以这里直接把每句的音频按时间轴摆进去,而不是首尾相接)
    inputs = []
    for l in lines:
        inputs += ["-i", l["mp3"]]
    # 用 adelay 把每句摆到它的时间点上
    filters = []
    for k, l in enumerate(lines):
        filters.append(f"[{k}:a]adelay={int(l['start']*1000)}|{int(l['start']*1000)},"
                       f"apad=pad_dur=0.1[a{k}]")
    graph = "".join(f"[a{k}]" for k in range(len(lines)))
    mix = "".join(f"[a{k}]" for k in range(len(lines)))
    # apad=whole_dur + atrim:把音轨补到成片的总长。
    # 不补的话音轨比视频短一片尾(2.75s),而 mux 用了 -shortest,
    # 视频会被一起截短 —— 角标时长(ffprobe 实测)也就跟着错了。
    fc = (";".join(filters) +
          f";{mix}amix=inputs={len(lines)}:normalize=0[mixout];"
          f"[mixout]apad=whole_dur={total},atrim=0:{total}[aout]")
    raw = f"/tmp/promo_minimax/voice-raw-{variant}.wav"
    voice = f"/tmp/promo_minimax/voice-{variant}.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error"] + inputs +
                   ["-filter_complex", fc, "-map", "[aout]", "-ar", "48000",
                    "-ac", "1", "-c:a", "pcm_s16le", raw], check=True)

    stats, gain = _normalize_voice(raw, voice)
    print(f"[{variant}] 响度归一 gain={gain:+.2f}dB → "
          f"{stats['I']:.1f} LUFS / TP {stats['TP']:.1f} dBTP", flush=True)

    out_mp4 = f"{OUT}/shadow-ebook-promo-{variant}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                    "-i", f"{fdir}/f%05d.png", "-i", voice,
                    "-c:v", "libx264", "-preset", "slow", "-crf", "20",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
                    "-shortest", "-movflags", "+faststart", out_mp4], check=True)
    print("成片:", out_mp4, flush=True)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "9x16"
    render(which)
