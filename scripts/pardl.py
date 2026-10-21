#!/usr/bin/env python3
"""并行分块下载 + 逐块校验。

为什么需要它:HuggingFace 的 CDN 在国内单线程只有 30KB/s,
141MB 的模型要下一个多小时。走 hf-mirror.com + 16 路并发能到 1MB/s,
89 秒下完。

但**裸 bash 并行会少几 MB** —— 最后一块没落全,表现是加载时报
「model.bin 损坏」,而且很难查。所以这里逐块校验大小,少一块就重下那一块。

用法:
    pardl.py <url> <out> <total_bytes> [并发数]

例:
    URL="https://hf-mirror.com/Systran/faster-whisper-base/resolve/main/model.bin"
    FINAL=$(curl -sL -o /dev/null -m 25 -w '%{url_effective}' "$URL")
    python3 scripts/pardl.py "$FINAL" ~/.cache/shadow-whisper/base/model.bin 145217532 16

断点续传:重跑同一条命令即可 —— 已下全的块会直接跳过。
"""
import os
import sys
import threading
import time
import urllib.request

CHUNK_RETRIES = 4


def fetch_range(url, path, start, end, idx):
    """把 [start, end] 这段下到 path(追加模式,支持续传)。"""
    want = end - start + 1
    for attempt in range(CHUNK_RETRIES):
        have = os.path.getsize(path) if os.path.exists(path) else 0
        if have >= want:
            return True
        req = urllib.request.Request(
            url, headers={'Range': f'bytes={start + have}-{end}'})
        try:
            with urllib.request.urlopen(req, timeout=60) as r, open(path, 'ab') as f:
                while True:
                    buf = r.read(1 << 16)
                    if not buf:
                        break
                    f.write(buf)
        except Exception as e:
            print(f'  块{idx} 第{attempt + 1}次失败: {e}')
            time.sleep(1.5)
    have = os.path.getsize(path) if os.path.exists(path) else 0
    ok = have >= want
    if not ok:
        print(f'  块{idx} 最终仍不完整: {have}/{want}')
    return ok


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(2)
    url, out, total = sys.argv[1], sys.argv[2], int(sys.argv[3])
    n = int(sys.argv[4]) if len(sys.argv) > 4 else 16
    d = out + '.parts'
    os.makedirs(d, exist_ok=True)
    size = (total + n - 1) // n
    t0 = time.time()

    threads = []
    for i in range(n):
        s = i * size
        if s >= total:
            break
        e = min(s + size - 1, total - 1)
        p = os.path.join(d, f'p{i:03d}')
        t = threading.Thread(target=fetch_range, args=(url, p, s, e, i))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    # 拼接 + 校验
    total_got = 0
    with open(out, 'wb') as fo:
        for i in range(n):
            p = os.path.join(d, f'p{i:03d}')
            if not os.path.exists(p):
                continue
            with open(p, 'rb') as fi:
                while True:
                    buf = fi.read(1 << 20)
                    if not buf:
                        break
                    fo.write(buf)
                    total_got += len(buf)
    print(f'拼完 {total_got} / {total} bytes  ({total_got / 1048576:.1f}MB)  '
          f'耗时 {time.time() - t0:.0f}s')

    if total_got != total:
        print('❌ 大小对不上,不能用。分块还留在', d, ',重跑同一条命令会续传')
        sys.exit(1)
    print('✅ 大小正确')
    for i in range(n):
        try:
            os.unlink(os.path.join(d, f'p{i:03d}'))
        except OSError:
            pass
    try:
        os.rmdir(d)
    except OSError:
        pass


if __name__ == '__main__':
    main()
