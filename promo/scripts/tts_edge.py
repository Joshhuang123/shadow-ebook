#!/usr/bin/env python3
"""edge-tts 旁白(沉稳新闻播报男声)—— MiniMax 上游 429 时的**同规格**兜底。

和 tts_minimax.py 输出同一个 timeline.json 格式,所以下游
(video_mm.py / covers.py)完全不用改,换条命令就换音色。

为什么要有这个
--------------
josh-media skill 锁死的是「沉稳高管」那个音色(MiniMax 的
Chinese (Mandarin)_Reliable_Executive)。但 MiniMax 的 TTS 上游
在 2026-10-25 整整一个下午都在 429:
  · 官方链路和国内镜像(mcode-tools-cn)同一个上游,一起 429
  · 静默 15 分钟再试,一样 429
  · batch 和单句都一样
所以先交付一条**完整**能发的片子,音色用 edge-tts 的
zh-CN-YunyangNeural(News · Professional · Reliable —— 新闻播报腔,
沉稳、可靠),等 MiniMax 恢复后重跑 tts_minimax.py 就是真·沉稳高管。

音色不换着来:一整条片子一个音色,中途换声音是最难听的做法。
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 仓库根的 venv(不是 promo/venv —— 那是脚本目录)
VENV = os.path.join(os.path.dirname(ROOT), "venv", "bin")
EDGE = os.path.join(VENV, "edge-tts")
OUT = "/tmp/promo_edge"
VOICE = "zh-CN-YunyangNeural"
RATE = "-8%"          # 比默认慢一点,更沉稳

os.makedirs(OUT, exist_ok=True)

LINES = [
    (1, "孩子的英语录音,不上传云端。"),
    (1, "这是我给自己孩子做的英语阅读器,叫影子电子书。"),
    (1, "家里一台电脑就够,平板打开浏览器就能用。"),
    (2, "读起来是纸的排版,不是网页。"),
    (2, "点单词查释义,查过的词自动进生词本。"),
    (2, "上一句下一句,一句一句地走,走到底自动翻页。"),
    (3, "跟读这块花的时间最多。"),
    (3, "别的软件只说你这个词读错了。"),
    (3, "它直接说,这个 o 的音还不稳,长 o 像 go。"),
    (3, "词有两万个,音只有几十个,音才是能练的东西。"),
    (4, "知识图谱把教材、考纲和掌握度画在一张图上。"),
    (4, "这一章要会什么,先要会什么,一眼看到。"),
    (5, "家长页是诊断,不是报表。"),
    (5, "哪个音还不稳,哪个知识点没学会,直接列出来。"),
    (6, "不用云端,书和孩子的录音都在自己家里。"),
    (6, "代码开源了,GitHub 上就能找到。"),
    (6, "你更想要哪一种,整屏读,还是一句一句跟读?评论区说说。"),
]


def run(cmd, timeout=180):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def dur(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "default=nw=1:nk=1", path]).stdout.strip())


def main():
    results = []
    for i, (scene, text) in enumerate(LINES, 1):
        name = f"s{i:02d}"
        mp3 = f"{OUT}/{name}.mp3"
        if not (os.path.exists(mp3) and os.path.getsize(mp3) > 1000):
            p = run([EDGE, "--voice", VOICE, f"--rate={RATE}", "--text", text,
                     "--write-media", mp3], timeout=120)
            if p.returncode != 0 or not os.path.exists(mp3):
                raise RuntimeError(f"{name} 合成失败: {p.stderr[:200]}")
        d = dur(mp3)
        results.append({"i": i, "scene": scene, "text": text, "mp3": mp3, "dur": d})
        print(f"  [{name}] {d:.2f}s  {text[:20]}", flush=True)

    t = 0.0
    for k, r in enumerate(results):
        if k and r["scene"] != results[k - 1]["scene"]:
            t += 0.75
        elif k:
            t += 0.30
        r["start"] = round(t, 3)
        t += r["dur"]
        r["end"] = round(t, 3)
    total = round(t + 2.75, 3)
    os.makedirs("/tmp/promo_minimax", exist_ok=True)
    json.dump({"lines": results, "total": total, "voice": VOICE},
              open("/tmp/promo_minimax/timeline.json", "w"), ensure_ascii=False, indent=1)
    chars = sum(len(r["text"]) for r in results)
    print(f"\n总时长 {total:.2f}s(含片尾 2.75s) | {chars} 字 "
          f"→ {chars/total:.2f} 字/秒(端到端) | 音色 {VOICE}")


if __name__ == "__main__":
    main()
