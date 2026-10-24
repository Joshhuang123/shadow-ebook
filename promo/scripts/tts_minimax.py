#!/usr/bin/env python3
"""逐句合成 MiniMax 沉稳高管旁白,并重建时间轴。

纪律(照 josh-media skill):
  · 音色锁死 Chinese (Mandarin)_Reliable_Executive,全系列一个音色
  · **串行**,句与句之间 sleep 1 —— 上游限流严重,批量并发必吃 429
  · 参数走 --args-file,绕开 shell 转义
  · 吃 429 固定 30 秒心跳(不用指数退避),重试最多 80 次
  · 响度归一到 -16 LUFS(在 ffmpeg 那一步做)
  · 句间静音 0.30s、场间静音 0.75s、片尾 2.75s
"""
import json
import os
import subprocess
import sys
import time

VOICE = "Chinese (Mandarin)_Reliable_Executive"
# mcode-tools-cn 是国内镜像。官方那条链路的上游 TTS 经常 429
# (实测 17 句只出来 12 句,静默 5 分钟也不恢复),国内镜像同声同色不限流。
MCODE = os.environ.get("MCODE_BIN", "mcode-tools-cn")
OUT = "/tmp/promo_minimax"
os.makedirs(OUT, exist_ok=True)

# (场号, 句子)
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

ARGS = "/tmp/minimax_tts_args.json"


def run(cmd, timeout=180):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def tts_one(text, name, attempt_limit=80):
    """合成一句。吃 429 就固定 30 秒心跳重试。"""
    for attempt in range(attempt_limit):
        with open(ARGS, "w") as f:
            json.dump({"text": text, "voice_id": VOICE, "output_file": f"{name}.mp3"},
                      f, ensure_ascii=False)
        p = run([MCODE, "connector", "call",
                 "connector__matrix__synthesize_speech", "--args-file", ARGS], timeout=240)
        out = (p.stdout or "").strip()
        if p.returncode == 0 and '"node_id"' in out:
            try:
                d = json.loads(out)
                if d.get("node_id"):
                    return d["node_id"]
            except Exception:
                pass
        # 上游限流会直接把 code:429 写在 stdout 里,退出码还是 0
        msg = out or (p.stderr or "")
        if "429" in msg or "rate-limit" in msg.lower() or p.returncode != 0:
            try:
                j = json.loads(out)
                msg = j.get("message", msg)
            except Exception:
                pass
            print(f"  [{name}] 第{attempt+1}次 429,30 秒心跳重试: {msg[:90]}", flush=True)
            time.sleep(30)
            continue
        raise RuntimeError(f"TTS 失败: {(p.stderr or out)[:300]}")
    raise RuntimeError("重试次数用尽")


def fetch(node_id, name):
    p = run([MCODE, "get_asset_url", node_id], timeout=120)
    d = json.loads(p.stdout)
    url = d.get("download_url")
    dest = f"{OUT}/{name}.mp3"
    r = run(["curl", "-sL", "-o", dest, url], timeout=180)
    if not os.path.exists(dest) or os.path.getsize(dest) < 1000:
        raise RuntimeError(f"下载失败: {dest}")
    return dest


def dur(path):
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path], timeout=60)
    return float(p.stdout.strip())


def main():
    results = []
    for i, (scene, text) in enumerate(LINES, 1):
        name = f"s{i:02d}"
        mp3 = f"{OUT}/{name}.mp3"
        if os.path.exists(mp3) and os.path.getsize(mp3) > 1000:
            print(f"  [{name}] 已有,跳过", flush=True)
        else:
            print(f"  [{name}] {text[:16]}…", flush=True)
            nid = tts_one(text, name)
            fetch(nid, name)
            time.sleep(1)          # 串行:句与句之间 sleep 1
        d = dur(mp3)
        results.append({"i": i, "scene": scene, "text": text, "mp3": mp3, "dur": d})
        print(f"      {d:.2f}s", flush=True)

    # 重建时间轴:句间 0.30s、场间 0.75s、片尾 2.75s
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
    json.dump({"lines": results, "total": total, "voice": VOICE},
              open(f"{OUT}/timeline.json", "w"), ensure_ascii=False, indent=1)
    print(f"\n总时长(含片尾 2.75s): {total:.2f}s  "
          f"实算 {sum(len(r['text']) for r in results)} 字 "
          f"→ {sum(len(r['text']) for r in results)/total:.3f} 字/秒(端到端)")


if __name__ == "__main__":
    main()
