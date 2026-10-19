"""连续朗读(「读一句」自己往下读)的推进逻辑守护。

这个 bug 是 2026-10-19 实测抓出来的,不是理论风险:

`playCurrentSentence` 里,读完之后的分支是这样分叉的 ——
  · 普通模式:调用 `advance()` 把游标推到下一句,然后停下等下一次按键;
  · 连续模式:调用 `playCurrentSentence()` 接着读。

**连续模式那条分支忘了先把游标 +1**。而 `playCurrentSentence` 读的是
`sentences[currentSentenceIndex]` —— 游标没动,它就把同一句又读了一遍。
表现是:点「连续朗读」之后,平板把同一句话反复念,永远念不到下一句。
在浏览器里用真实鼠标事件 + 抓 `new Audio()` 抓出来的:连续三次播放的
音频文件名完全相同。

这类 bug 在纯代码审阅里极难看出来(两行都"读起来对"),但对孩子是致命的:
「自动往下读」这个功能等于没有。删掉一行就静默回归,所以写成测试钉住。
"""
from pathlib import Path
import re

INDEX_JS = Path(__file__).resolve().parent.parent / 'web' / 'js' / 'index.js'


def _play_current_sentence_body(src: str) -> str:
    """截出 playCurrentSentence 函数体。

    结束点用「下一个同缩进的顶层 function」,避免把后面的函数也切进来。
    """
    start = src.index('async function playCurrentSentence')
    rest = src[start + len('async function playCurrentSentence'):]
    m = re.search(r'\n        (?:async )?function ', rest)
    return rest[:m.start()] if m else rest


def test_index_js_exists():
    assert INDEX_JS.exists(), 'web/js/index.js 不见了'


def test_advance_returns_whether_it_moved():
    """advance() 必须回报「有没有推进」。

    连读分支靠这个返回值判断「已经读到最后一句,该停了」。
    没有返回值时,读到书尾会又播一遍最后一句。
    """
    src = INDEX_JS.read_text(encoding='utf-8')
    body = _play_current_sentence_body(src)
    assert 'const advance = () =>' in body, 'advance() 不见了'
    adv = body[body.index('const advance = () =>'):]
    adv = adv[:adv.index('\n            };')]
    assert 'return true' in adv, 'advance() 没有在推进成功时 return true'
    assert 'return false' in adv, 'advance() 没有在到书尾时 return false'


def test_continuous_mode_advances_before_reading_next():
    """连续朗读分支:必须先 advance() 再读下一句。

    顺序反了就是「原地复读同一句」—— 见本文件开头的 bug 记录。
    """
    src = INDEX_JS.read_text(encoding='utf-8')
    body = _play_current_sentence_body(src)
    assert 'if (readAloneMode) {' in body, '连续朗读分支不见了'
    branch = body[body.index('if (readAloneMode) {'):]
    branch = branch[:branch.index('} else {')]

    i_advance = branch.find('advance()')
    i_play = branch.find('playCurrentSentence(')
    assert i_advance != -1, ('连续朗读分支里没有 advance():游标不会推进,'
                             '会一直复读同一句')
    assert i_play != -1, '连续朗读分支里没有接着读下一句的调用'
    assert i_advance < i_play, ('连续朗读必须先 advance() 再 playCurrentSentence():'
                                '反了就是拿同一个 currentSentenceIndex 再读一遍')


def test_continuous_mode_stops_at_last_sentence():
    """读到书尾要停,不能循环。"""
    src = INDEX_JS.read_text(encoding='utf-8')
    body = _play_current_sentence_body(src)
    branch = body[body.index('if (readAloneMode) {'):]
    branch = branch[:branch.index('} else {')]
    assert 'if (!advance()) return' in branch, (
        '连续朗读没有在书尾停下 —— 到最后一句会反复循环')
