"""跟读链路的静态约束:别再把孩子的录音送去云端。

背景:
  跟读曾经用浏览器的 SpeechRecognition —— 音频发到 Google 云端。
  ① 和产品承诺「孩子的英语录音,不上传云端」直接矛盾;
  ② 国内访问不到它的识别服务,结果永远等不到 →「读了没什么反应」;
  ③ Safari/iPad 根本没有这个 API。

这几条是回归护栏:哪天有人又用回 SpeechRecognition,这里会红。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def _read(rel: str) -> str:
    return (WEB / rel).read_text(encoding="utf-8")


def _code_only(src: str) -> str:
    """去掉注释 —— 注释里提一嘴 SpeechRecognition 不算违规。"""
    out = []
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
            continue
        out.append(line.split("//")[0])
    return "\n".join(out)


def test_reader_followread_does_not_use_browser_cloud_asr():
    """阅读器侧栏的跟读不能靠浏览器的 SpeechRecognition。"""
    src = _code_only(_read("js/index.js"))
    assert "SpeechRecognition" not in src, \
        "index.js 还在用浏览器 SpeechRecognition:音频会被发到云端"
    assert "webkitSpeechRecognition" not in src, \
        "index.js 还在用浏览器 SpeechRecognition:音频会被发到云端"


def test_reader_followread_uses_local_asr_endpoint():
    """跟读要走到本地的 /api/recording/feedback(faster-whisper)。"""
    src = _read("js/index.js")
    assert "/api/recording/feedback" in src, \
        "index.js 的跟读没走本地 ASR 接口"


def test_both_pages_load_mic_guard():
    """两个页面都要加载麦克风检测,否则失败时又是「点了没反应」。"""
    for page in ("index.html", "tutor.html"):
        assert "/js/mic.js" in _read(page), f"{page} 没加载 mic.js"


def test_mic_guard_has_no_external_hosts():
    """mic.js 只能本地判断,不许把录音送去任何外部地址。"""
    src = _code_only(_read("js/mic.js"))
    for bad in ("http://", "https://"):
        # 只允许出现给用户看的本机地址提示
        for line in src.splitlines():
            if bad in line:
                assert "localhost" in line, \
                    f"mic.js 里出现了外链 {bad}:{line.strip()}"


def test_reader_sidebar_has_phoneme_detail_slot():
    """阅读器侧栏要能显示音素级归因(和宣传片说的一致)。"""
    html = _read("index.html")
    assert 'id="pronunciation-detail"' in html, \
        "侧栏缺 pronunciation-detail 容器,音素归因没地方显示"
    src = _read("js/index.js")
    assert "renderPronunciationDetail" in src
    assert "phoneme_tips" in src, "侧栏没读服务端的音素归因"
