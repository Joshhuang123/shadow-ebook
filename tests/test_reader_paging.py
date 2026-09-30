"""tests/test_reader_paging.py — 翻页必须能连续跨章,不能卡在章末。

背景(2026-09-30 修复的真实 bug,用户报的「这本书不可能这么短,只有十四页」):
    selectChapter 原来写的是 `sentences = bookData.chapters[i].sentences`,
    于是 `sentences` 只装**当前一章**。nextPage 在本章末屏就被夹住,
    「下一页」按钮变灰 —— 想读下一章必须打开抽屉手动点目录。

    实测那本书的第 0 章(Copyright)正好 14 句,顶栏 `1 / 14` 被读成
    「这本书一共 14 页」,于是判定书被截断了。实际上 21 章 778 句都在库里。

修法:加载时把全书拍平成一条句子流 + chapterStarts,游标是全书下标。
      章名/目录高亮由 chapterIndexOf(游标) 反推,翻页自然跨章。

每屏句数后来改成动态(见 tests/test_reading_density.py),所以这里把
3/4/5/7/10 五档全跑一遍 —— 只测一档的话,换档之后坏掉没人会发现。

本测试用 node + 最小 DOM stub 真跑 web/js/index.js —— 这类 bug 肉眼看不出来,
纯靠翻页逻辑单测又绕开了真实的 updateDisplay 链路。

键位也是同一套 harness 里派发真事件验的:← → 走句子不走整屏
(2026-09-30 用户报「还是上下页」),按钮才是走整屏。
"""
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HARNESS = Path(__file__).resolve().parent / 'reader_paging_harness.js'

# 每屏句数会随孩子水平变化,五档都要成立
DENSITIES = [3, 4, 5, 7, 10]

pytestmark = pytest.mark.skipif(shutil.which('node') is None,
                                reason='需要 node 才能跑前端翻页测试')


@pytest.fixture(scope='module')
def result():
    proc = subprocess.run(['node', str(HARNESS)], capture_output=True, text=True,
                          cwd=str(REPO), timeout=120)
    assert proc.returncode == 0, f'翻页测试失败:\n{proc.stdout}\n{proc.stderr}'
    return proc.stdout


@pytest.mark.parametrize('per', DENSITIES)
def test_page_count_is_exact(result, per):
    """屏数 = ceil(全书句数 / 每屏句数),不多不少。"""
    assert f'✓ 每屏 {per} 句:屏数正确' in result, result


@pytest.mark.parametrize('per', DENSITIES)
def test_every_sentence_is_shown_exactly_once(result, per):
    """真正的不变量:全书每一句都恰好出现在一屏上。

    「经过了第几章」是个坏代理 —— 末章只有 3 句而每屏 10 句时,
    它永远不会成为某一屏的首句,却实打实印在那一屏上。
    """
    assert f'✓ 每屏 {per} 句:全书每一句都显示到' in result, result
    assert f'✓ 每屏 {per} 句:没有句子重复显示' in result, result


@pytest.mark.parametrize('per', DENSITIES)
def test_last_page_contains_the_final_sentence(result, per):
    """末屏必须盖住全书最后一句 —— 「翻完了但没看到结尾」是常见漏页。"""
    assert f'✓ 每屏 {per} 句:末屏包含全书最后一句' in result, result


@pytest.mark.parametrize('per', DENSITIES)
def test_chapter_lookup_and_crossing(result, per):
    """每章下标可定位,且本章末句翻一下就进下一章。"""
    assert f'✓ 每屏 {per} 句:每章下标都能定位  21/21' in result, result
    assert f'✓ 每屏 {per} 句:从本章末句翻页进下一章' in result, result


@pytest.mark.parametrize('per', DENSITIES)
def test_progress_still_stores_chapter_relative_index(result, per):
    """/api/progress 的约定是「第几章 + 该章第几句」,拍平后不能改成全书下标。"""
    assert f'✓ 每屏 {per} 句:进度存章内下标' in result, result
    assert 'chapter=2 sentence=5' in result, result


def test_fixture_matches_the_real_book(result):
    """fixture 复刻了真实故障的形状:21 章 778 句,第 0 章 14 句。

    旧代码下顶栏会显示「1 / 14」—— 正是用户报的「只有十四页」。
    """
    assert '全书 21 章 / 778 句 / 每屏 3 句 = 260 屏' in result, result


@pytest.mark.parametrize('per', DENSITIES)
def test_arrow_keys_step_by_sentence(result, per):
    """← → 走的是句子,不是整屏(用户 2026-09-30 明确要求)。

    这一组必须**真的派发按键**。早先一版只直调 nextSentence(),
    全绿 —— 而当时 keydown 里还接着 nextPage(),正是用户报的
    「← → 还是上下页」。故障在路由,不在函数,直调就绕开了。
    """
    assert f'✓ 每屏 {per} 句:按 → 只前进一句' in result, result
    assert f'✓ 每屏 {per} 句:按 ← 只后退一句' in result, result


@pytest.mark.parametrize('per', DENSITIES)
def test_page_turns_only_after_last_sentence(result, per):
    """页内挪动时正文不动(靠当前句高亮给反馈),越过本页末句才翻页。"""
    assert f'✓ 每屏 {per} 句:只在越过本页末句时才翻页' in result, result
    assert f'✓ 每屏 {per} 句:按 → 越过本页末句才翻页' in result, result


@pytest.mark.parametrize('per', DENSITIES)
def test_arrow_keys_stop_at_book_ends(result, per):
    """首句不能再往回,末句不能再往前,双向都要能走到全书每一句。"""
    assert f'✓ 每屏 {per} 句:在第一句处往回不动' in result, result
    assert f'✓ 每屏 {per} 句:在最后一句处往前不动' in result, result
    assert f'✓ 每屏 {per} 句:方向键能读到全书每一句  走到 778/778 句' in result, result


def test_arrow_keys_do_not_move_whole_page_per_density(result):
    """回归钉子:整屏回退在任一档都不该发生。

    旧代码下 press('ArrowLeft') 从 per+1 直接掉到 0,这里会红。
    """
    for per in DENSITIES:
        assert '✗ 每屏 %d 句:按 ← 只后退一句' % per not in result, result
        assert '✗ 每屏 %d 句:按 → 只前进一句' % per not in result, result


# === 查词弹窗 ===

def test_word_modal_shows_chinese_meaning(result):
    assert '✓ 查词:成功时弹出中文释义' in result, result
    assert '✓ 查词:音标显示为 /.../ 形式' in result, result


def test_word_modal_escapes_upstream_text(result):
    """释义来自上游,拼进 innerHTML 前必须转义。"""
    assert '✓ 查词:上游文本已转义' in result, result


def test_word_modal_distinguishes_network_from_not_found(result):
    """"词典连不上"和"没查到这个词"是两回事,不能都显示成「查询失败」。"""
    assert '✓ 查词:上游挂掉时提示网络而不是「没查到」' in result, result
    assert '✓ 查词:查无此词才说「没查到这个词」' in result, result
    assert '✓ 查词:自己家的接口也挂掉时提示检查网络' in result, result
