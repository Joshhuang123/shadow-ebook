#!/usr/bin/env python3
"""生成宣传图文卡片。

不用 AI 生成图 —— 素材是这个项目的**真实界面**,
卡片用项目自己的字体和纸面色,这样推出去的东西和打开的东西是同一套。
"""
import base64
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import CDP, launch, new_tab  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "padded")
OUT = os.path.join(ROOT, "cards")
os.makedirs(OUT, exist_ok=True)

# 项目自己的设计令牌(抄自 web/styles/tokens.css)
CSS = """
:root{
  --color-primary:#B86A4E; --primary-fill:#A55A40;
  --bg:#F4F1EA; --bg-card:#FCFBF8; --bg-dark:#EAE5DA;
  --text-primary:#2D2A26; --text-secondary:#5A544C;
  --tint-primary:rgba(184,106,78,.10);
  --rule:rgba(45,42,38,.09); --rule-strong:rgba(45,42,38,.16);
  --font-display:'Iowan Old Style','Palatino',Georgia,'Songti SC','STSong','SimSun','Source Han Serif SC','Noto Serif CJK SC',serif;
  --font-display-bold:'Iowan Old Style','Palatino',Georgia,'Songti SC Black','STSongti-SC-Black','Songti SC','STSong','SimSun','Source Han Serif SC','Noto Serif CJK SC',serif;
  --font-sans:-apple-system,BlinkMacSystemFont,'PingFang SC','Helvetica Neue','Segoe UI',Roboto,sans-serif;
  --paper-glow:
      radial-gradient(1100px 620px at 82% -6%, rgba(212,165,116,.11) 0%, transparent 62%),
      radial-gradient(820px 560px at 4% 102%, rgba(122,139,159,.07) 0%, transparent 60%);
  --paper-grain:
      repeating-linear-gradient(115deg, rgba(45,42,38,.014) 0px, rgba(45,42,38,.014) 1px, transparent 1px, transparent 3px),
      repeating-linear-gradient(35deg, rgba(45,42,38,.010) 0px, rgba(45,42,38,.010) 1px, transparent 1px, transparent 4px);
}
*{margin:0;padding:0;box-sizing:border-box;}
body{background:var(--bg);}
.card{
  position:relative;overflow:hidden;
  background:var(--paper-glow),var(--paper-grain),
             linear-gradient(135deg,var(--bg-gradient-start,#F7F4EE) 0%,var(--bg-gradient-end,#EDE6D9) 100%);
  color:var(--text-primary);font-family:var(--font-sans);
  -webkit-font-smoothing:antialiased;
}
.pad{padding:64px 68px;height:100%;display:flex;flex-direction:column;}

/* 小标签 */
.eyebrow{
  display:inline-flex;align-items:center;gap:10px;
  font-size:19px;font-weight:600;letter-spacing:.24em;
  color:var(--color-primary);margin-bottom:22px;
}
.eyebrow .dot{width:7px;height:7px;border-radius:50%;background:var(--color-primary);}
.eyebrow .bar{width:38px;height:1px;background:var(--rule-strong);}

/* 大标题 */
.title{
  font-family:var(--font-display-bold);font-weight:700;
  font-size:86px;line-height:1.12;letter-spacing:-.015em;
  color:var(--text-primary);margin-bottom:24px;
}
.title.small{font-size:58px;}
.sub{
  font-size:25px;line-height:1.7;color:var(--text-secondary);
  font-weight:300;max-width:22em;margin-bottom:28px;
}

/* 短句列表 */
.points{list-style:none;margin-bottom:28px;}
.points li{
  display:flex;align-items:flex-start;gap:13px;
  font-size:22px;line-height:1.6;color:var(--text-secondary);
  padding:8px 0;border-bottom:1px solid var(--rule);
}
.points li:last-child{border-bottom:none;}
.points .mark{color:var(--color-primary);font-weight:700;flex:0 0 auto;font-size:22px;line-height:1.62;}
.points b{color:var(--text-primary);font-weight:600;}

/* 真机截图:放在一个平板边框里 */
.device{
  position:relative;border-radius:18px;overflow:hidden;
  /* 底色用纸色:截图本身的页面底色也是纸色,contain 留白的地方
     和截图边缘无缝,看不出是拼上去的 */
  background:var(--bg);
  border:1px solid var(--rule-strong);
  box-shadow:0 18px 44px rgba(45,42,38,.13), 0 2px 6px rgba(45,42,38,.06);
  /* 固定 8:5 —— 素材就是这个比例,cover 正好严丝合缝,既不裁也不留白 */
  flex:0 0 auto;aspect-ratio:8/5;width:100%;
}
.device img{display:block;width:100%;height:100%;object-fit:cover;object-position:center top;}
.device.contain img{object-fit:contain;object-position:center;}
.device .cam{
  position:absolute;top:9px;left:50%;transform:translateX(-50%);
  width:5px;height:5px;border-radius:50%;background:rgba(45,42,38,.16);
}

/* 底部一行 */
.foot{
  margin-top:auto;padding-top:26px;border-top:1px solid var(--rule);
  font-size:21px;color:var(--text-secondary);letter-spacing:.01em;
  display:flex;align-items:center;justify-content:space-between;gap:18px;
}
.foot .mono{font-family:'SF Mono',Menlo,Consolas,monospace;font-size:19px;color:var(--color-primary);letter-spacing:.02em;}
.tags{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:34px;}
.tag{
  font-size:21px;padding:9px 18px;border:1px solid var(--rule-strong);
  border-radius:9999px;color:var(--text-secondary);background:rgba(255,255,255,.4);
}
.tag.on{color:var(--primary-fill);border-color:rgba(184,106,78,.4);background:var(--tint-primary);}
.big{font-family:var(--font-display-bold);font-weight:700;font-size:120px;line-height:1;letter-spacing:-.02em;}

/* —— 横版(X)—- */
.land{display:grid;grid-template-columns:44% 56%;height:100%;}
.land .left{padding:70px 54px 58px 72px;display:flex;flex-direction:column;}
.land .right{position:relative;overflow:hidden;background:var(--bg-card);}
.land .right img{width:100%;height:100%;object-fit:cover;object-position:top center;}
"""

PORTRAIT = """
<div class="card" style="width:1080px;height:1440px">
  <div class="pad">
    {eyebrow}
    <h1 class="title {tsize}">{title}</h1>
    {sub}
    {points}
    {tags}
    <div class="device {fit}">
      <img src="{shot}">
    </div>
    <div class="foot"><span>{foot}</span><span class="mono">{mono}</span></div>
  </div>
</div>
"""

LANDSCAPE = """
<div class="card land" style="width:1600px;height:900px">
  <div class="left">
    {eyebrow}
    <h1 class="title {tsize}">{title}</h1>
    {sub}
    {points}
    <div class="foot" style="margin-top:auto"><span>{foot}</span><span class="mono">{mono}</span></div>
  </div>
  <div class="right"><img src="{shot}"></div>
</div>
"""


def img(name):
    p = os.path.join(SHOTS, name)
    if not os.path.exists(p):
        return ""
    return "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()


def eyebrow(text):
    return f'<div class="eyebrow"><span class="dot"></span><span class="bar"></span><span>{text}</span></div>'


def points(items):
    if not items:
        return ""
    lis = "".join(f'<li><span class="mark">—</span><span>{t}</span></li>' for t in items)
    return f'<ul class="points">{lis}</ul>'


def tags(items):
    if not items:
        return ""
    return '<div class="tags">' + "".join(
        f'<span class="tag {"on" if o else ""}">{t}</span>' for t, o in items) + "</div>"


CARDS = [
    dict(
        name="01-cover", eyebrow="局域网 · 开源 · 家庭英语阅读器",
        title="影子电子书", tsize="",
        sub="孩子在平板上读英文、跟读<br>家长在电脑上看进度",
        points=[
            "逐句朗读,读一句自动接下一句",
            "跟读评分,定位到是哪个「音」不稳",
            "家长页看进度,学习数据留在家里",
        ], tags=[],
        shot="reader.png",
        foot="一台电脑服务全家平板 · 不用注册 · 数据留在家里",
        mono="shadow-ebook",
    ),
    dict(
        name="02-reader", eyebrow="阅读器",
        title="像书一样读", tsize="small",
        sub="不是把 PDF 塞进网页,是照着书的样子排的",
        points=[
            "纸面排版,一行 <b>40–50 个字</b>,不追着屏幕跑",
            "点单词查释义,查过的词自动进生词本",
            "「上一句 / 下一句」逐句走,走到底自动翻页",
        ],
        tags=[], shot="reader-sentence.png",
        foot="拖进 EPUB / PDF / TXT,自动分章分句",
        mono="阅读器",
    ),
    dict(
        name="03-shadow", eyebrow="跟读评分", fit="contain",
        title="读错了,告诉你是<br>哪个「音」不对", tsize="small",
        sub="不是「这个词读错了」——<br>是「<b>/f/</b> 还不稳:上齿轻咬下唇」",
        points=[
            "录音 → 转写 → 比对,全程本地算",
            "词级差异下沉到<b>音素</b>:音只有几十个,词有两万个",
            "答错哪个音,家长页直接列出来",
        ],
        tags=[], shot="tutor-feedback-card.png",
        foot="转写用 faster-whisper,不用装 torch,省 2.3GB",
        mono="跟读",
    ),
    dict(
        name="04-kg", eyebrow="知识图谱",
        title="教到哪、考到哪、<br>孩子会哪", tsize="small",
        sub="教材单元 → 前置知识点 → 考纲对照,一张图",
        points=[
            "新概念青少版 2A 的 9 个单元,逐个标出要会的语法",
            "故事书按<b>正文</b>抽知识点,不按目录名",
            "语法练习的成绩,实时回填成掌握度",
        ],
        tags=[], shot="tutor-mth.png",
        foot="小托福 / 剑桥通用五级考纲对照(本项目自整理)",
        mono="知识图谱",
    ),
    dict(
        name="05-parent", eyebrow="家长页",
        title="家长看到的是诊断,<br>不是报表", tsize="small",
        sub="读了哪本、哪个音还不稳、<br>哪个知识点没学会",
        points=[
            "发音上还不稳的音,带例词和怎么发",
            "已掌握 / 在学 / 要补,三档一眼看完",
            "学习记录一键导出 JSON / CSV",
        ],
        tags=[], shot="parent-panel.png",
        foot="家长密码保护,孩子看不到这一页",
        mono="家长页",
    ),
    dict(
        name="06-end", eyebrow="",
        title="一台电脑,<br>全家平板", tsize="",
        sub="不需要注册,不需要云端。<br>书、录音、学习记录,全在自己家里。",
        points=[],
        tags=[("局域网访问", True), ("可完全离线", True), ("开源", True), ("中文界面", False)],
        shot="shelf.png",
        foot="github.com/Joshhuang123/shadow-ebook",
        mono="MIT",
    ),
]


def render_html(card, landscape):
    d = dict(card)
    d["eyebrow"] = eyebrow(card["eyebrow"]) if card["eyebrow"] else ""
    d["sub"] = f'<p class="sub">{card["sub"]}</p>' if card["sub"] else ""
    d["points"] = points(card["points"])
    d["tags"] = tags(card["tags"])
    d["shot"] = img(card["shot"])
    d["fit"] = card.get("fit", "")
    tpl = LANDSCAPE if landscape else PORTRAIT
    return ("<!doctype html><html><head><meta charset='utf-8'><style>"
            + CSS + "</style></head><body>"
            + tpl.format(**d) + "</body></html>")


def main():
    landscape = "--landscape" in sys.argv
    only = [a for a in sys.argv[1:] if a.startswith("--only=")]
    only = only[0].split("=", 1)[1] if only else None
    W, H = (1600, 900) if landscape else (1080, 1440)
    port = 9600 if landscape else 9601
    proc = launch(port=port, profile="/tmp/chrome-cards", width=W, height=H)
    try:
        tab = new_tab(port=port, url="about:blank")
        cdp = CDP(tab["webSocketDebuggerUrl"])
        cdp.call("Runtime.enable")
        cdp.call("Page.enable")
        for card in CARDS:
            if only and only not in card["name"]:
                continue
            html = render_html(card, landscape)
            path = f"/tmp/promo-card-{card['name']}.html"
            open(path, "w").write(html)
            cdp.call("Page.navigate", {"url": "file://" + path})
            time.sleep(1.4)
            # 锁定视口:窗口高度会被浏览器装饰吃掉 80 多 px,
            # 不锁的话卡片底部(页脚)会被裁掉
            cdp.call("Emulation.setDeviceMetricsOverride", {
                "width": W, "height": H, "deviceScaleFactor": 1, "mobile": False})
            time.sleep(0.7)
            s = cdp.call("Page.captureScreenshot", {"format": "png"})
            suffix = "-x" if landscape else ""
            out = f"{OUT}/{card['name']}{suffix}.png"
            with open(out, "wb") as f:
                f.write(base64.b64decode(s["data"]))
            print("  ✓", os.path.basename(out))
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
