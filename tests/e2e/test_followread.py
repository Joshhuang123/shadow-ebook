"""跟读链路的 e2e:真的录一段,真的走本地 ASR,真的有反馈。

背景(为什么这个用例必须存在):
  跟读功能之前用浏览器的 SpeechRecognition —— ① 音频发到 Google 云端,
  和「孩子的录音不上传云端」直接矛盾;② 国内访问不到它的识别服务,
  结果永远等不到 →「读了没什么反应」;③ Safari/iPad 根本没这个 API。
  现在统一走本地 faster-whisper(/api/recording/feedback)。

本用例把麦克风换成一个假的:浏览器里注入一段预录的音频当麦克风输入
(孩子把 walking 读成 working),走完整的
  录音 → 上传 → 本地转写 → 词级差异 → 音素归因 → 界面反馈
链路,断言界面真的出现了「/AO/ 还不稳」。

**跑在隔离实例上**(自己的临时 DB):跟读会写进度和音素掌握度,
共用生产 data/shadow.db 会把假的记录混进孩子真实数据里。

音频 fixture:tests/fixtures/child_working.mp3.b64
  base64 编码的 mp3(say -v Samantha 合成的
  "he and Annie were working home from school")
"""
from __future__ import annotations

import base64
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "child_working.mp3.b64"

# 目标句在 /tutor 的 MTH29 Chapter 1 里
TARGET = "He and Annie were walking home from school."

# 最小图谱数据(CMUdict 手工切片)。
# walking / working 只差一个 /AO/ —— 归因要能算出「walking 里的 /AO/ 还不稳」。
KG_WORD_PHONEMES = {
    "he": ["HH", "IY"],
    "and": ["AE", "N", "D"],
    "annie": ["AE", "N", "IY"],
    "were": ["W", "ER"],
    "walking": ["W", "AO", "K", "IH", "NG"],
    "working": ["W", "ER", "K", "IH", "NG"],
    "home": ["HH", "OW", "M"],
    "from": ["F", "R", "AH", "M"],
    "school": ["S", "K", "UW", "L"],
}

# (音素 id, 展示名, 提示语, 是不是元音)
KG_PHONEME_NODES = [
    ("AO", "AO", "长 o(像 go)", True),
    ("ER", "ER", "卷舌的 er(像 her)", True),
    ("IH", "IH", "短 i(像 it)", True),
    ("IY", "IY", "长 i(像 eat)", True),
    ("AE", "AE", "开口的 a(像 cat)", True),
    ("AH", "AH", "短 a(像 cup)", True),
    ("OW", "OW", "双元音 ow(像 how)", True),
    ("UW", "UW", "长 u(像 moon)", True),
    ("N", "N", "鼻音 n(像 no)", False),
    ("NG", "NG", "鼻音 ng(像 sing)", False),
    ("K", "K", "k(像 cat)", False),
    ("W", "W", "w(像 we)", False),
    ("HH", "HH", "h(像 hat)", False),
    ("D", "D", "d(like do)", False),
    ("F", "F", "f(像 fan)", False),
    ("R", "R", "r(像 red)", False),
    ("M", "M", "m(像 map)", False),
    ("S", "S", "s(像 sun)", False),
    ("L", "L", "l(like leg)", False),
]


def _b64() -> str:
    return FIXTURE.read_text(encoding="utf-8").strip()


FAKE_MIC_JS = """
(() => {
  const B64 = "%s";
  const bin = atob(B64);
  const raw = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) raw[i] = bin.charCodeAt(i);

  window.__fakeMicStream = null;
  navigator.mediaDevices.getUserMedia = async () => {
    if (window.__fakeMicStream) return window.__fakeMicStream;
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const audio = await ctx.decodeAudioData(raw.buffer.slice(0));
    const dest = ctx.createMediaStreamDestination();
    const src = ctx.createBufferSource();
    src.buffer = audio;
    // 只播一遍:循环会让录音里出现两遍整句,词对齐就乱了,
    // 音素归因也会跟着失准。延迟 0.3s 起播,保证 MediaRecorder
    // 已经在录了才开口,不会把第一个音节切掉。
    src.loop = false;
    src.connect(dest);
    src.start(ctx.currentTime + 0.3);
    window.__fakeMicStream = dest.stream;
    return dest.stream;
  };
})();
"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def iso_app(tmp_path_factory):
    """起一个自己的 Flask 实例,用临时 DB(不碰 data/shadow.db)。

    用项目的 venv python 起 —— faster-whisper 只装在 venv 里,
    拿系统 python 起的话 ASR 直接不可用,这个用例就测不到真东西了。
    """
    data_dir = tmp_path_factory.mktemp("shadow_iso")
    port = _free_port()
    venv_python = ROOT / "venv" / "bin" / "python"
    python_exe = str(venv_python) if venv_python.exists() else sys.executable

    # 最小图谱:目标句用到的那几个词的音素序列(CMUdict 的手工切片)。
    # 全量图谱由 scripts/build_kg.py 建,太重;这里只要够归因到 /AO/ 就够。
    seed_file = data_dir / "kg_seed.json"
    seed_file.write_text(
        json.dumps({"nodes": KG_PHONEME_NODES, "words": KG_WORD_PHONEMES},
                   ensure_ascii=False),
        encoding="utf-8",
    )

    code = (
        "import sys, json; sys.path.insert(0, %r); "
        "from pathlib import Path; "
        "from extensions import db; "
        "db.DATA_DIR = Path(%r); "
        "db.DB_PATH = db.DATA_DIR / 'shadow.db'; "
        "db.BOOKS_JSON_DIR = db.DATA_DIR / 'books'; "
        "db.init_db(); "
        "from extensions.kg import upsert_nodes, upsert_edges; "
        "d = json.loads(Path(%r).read_text(encoding='utf-8')); "
        "upsert_nodes([(f'phoneme:{ph}', 'phoneme', label, 1, "
        "               {'hint': hint, 'vowel': vowel}) "
        "              for ph, label, hint, vowel in d['nodes']]); "
        "upsert_edges([(f'word:{w}', 'contains', f'phoneme:{ph}', 1.0) "
        "               for w, phs in d['words'].items() for ph in phs]); "
        "from app import app; "
        "import logging; logging.getLogger('werkzeug').setLevel(logging.WARNING); "
        "app.run(host='127.0.0.1', port=%d, debug=False, use_reloader=False)"
    ) % (str(ROOT), str(data_dir), str(seed_file), port)
    proc = subprocess.Popen([python_exe, "-c", code], cwd=str(ROOT))
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/healthz", timeout=1) as r:
                if r.status < 500:
                    break
        except Exception:
            time.sleep(0.3)
    else:
        proc.terminate()
        raise RuntimeError("isolated app did not start")
    yield base
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
def fake_mic(page, iso_app):
    """在页面脚本跑之前注入假麦克风。"""
    # 真权限也给一份:注入失败时能看出是"权限"问题,而不是"覆盖没生效"
    page.context.grant_permissions(["microphone"], origin=iso_app)
    page.add_init_script(FAKE_MIC_JS % _b64())
    return page


def _open_target_sentence(page, app_url) -> None:
    """切到 MTH29 → Chapter 1 → 翻到 walking 那句。

    不能假设「翻 3 次」—— 上次读到哪里会被 restore 回来,
    起始句不确定,所以按句子文本找,不是按次数。
    """
    page.goto(app_url + "/tutor")
    page.click('[data-action="selectBook"][data-arg="mth29"]')
    page.wait_for_selector("#chapter-list .unit-item", timeout=15000)
    page.click("#chapter-list .unit-item:first-child")
    page.wait_for_selector("#practice-view:not(.hidden)", timeout=15000)

    for _ in range(20):
        text = page.inner_text("#sentence-text")
        if "walking" in text:
            return
        page.click("#btn-next")
        page.wait_for_timeout(120)
    raise AssertionError(f"翻不到目标句,当前:{page.inner_text('#sentence-text')}")


def test_followread_records_and_reports_phoneme(fake_mic, iso_app):
    """读一句 → 本地 ASR → 界面出现音素级归因(不是静默)。"""
    page = fake_mic
    _open_target_sentence(page, iso_app)

    page.click("#btn-record")
    # 录 2.9 秒:假麦克风 0.3s 起播、整句约 2s,后面留一点静音尾巴
    page.wait_for_timeout(2900)
    page.click("#btn-stop")

    # 本地 ASR 要跑一会儿(首次要加载模型)。
    # 两步等:先等「正在分析发音…」这个占位真的出现(录音停了才会开始分析),
    # 再等它被真正结果换掉 —— 只等「占位消失」会撞上「还没渲染」的空档。
    page.wait_for_function(
        "() => { const el = document.getElementById('feedback-content');"
        " return !!el && el.textContent.includes('正在分析发音'); }",
        timeout=20000,
    )
    page.wait_for_function(
        "() => { const el = document.getElementById('feedback-content');"
        " return !!el && el.textContent.trim() !== ''"
        " && !el.textContent.includes('正在分析发音'); }",
        timeout=90000,
    )
    content = page.inner_text("#feedback-content")

    assert "working" in content, f"转写结果里应出现孩子读的 working,实际:\n{content}"
    assert "AO" in content, f"应指出 walking 里的 /AO/ 不稳,实际:\n{content}"
    assert "walking" in content, f"应点名是 walking 这个词,实际:\n{content}"


def test_mic_unavailable_shows_reason_not_silence(page, iso_app):
    """拿不到麦克风时,页面要说清原因 —— 不是「点了没反应」。

    这里模拟局域网 IP 直连 http 的情况:浏览器不给 navigator.mediaDevices。
    """
    page.add_init_script(
        # 复现「局域网 IP 直连 http」的完整症状:
        # isSecureContext=false → navigator.mediaDevices 整个没有
        "Object.defineProperty(window, 'isSecureContext', "
        "{ get: () => false, configurable: true });"
        "Object.defineProperty(navigator, 'mediaDevices', "
        "{ get: () => undefined, configurable: true });"
    )
    page.goto(iso_app + "/tutor")
    page.click('[data-action="selectBook"][data-arg="mth29"]')
    page.wait_for_selector("#chapter-list .unit-item", timeout=15000)
    page.click("#chapter-list .unit-item:first-child")
    page.wait_for_selector("#practice-view:not(.hidden)", timeout=15000)

    page.click("#btn-record")
    page.wait_for_timeout(500)
    status = page.inner_text("#record-status")

    assert status and "HTTPS" in status, f"应提示当前地址不是 HTTPS,实际:\n{status}"
    # 不能是一句含糊的「无法访问麦克风」
    assert "无法访问麦克风" not in status, f"提示应具体到原因,实际:\n{status}"
