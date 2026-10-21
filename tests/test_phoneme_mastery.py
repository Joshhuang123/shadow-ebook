"""音素层:跟读读不准,到底是不哪个**音**。

跟读反馈给的是词级差异 ——「你把 castle 读成了 cassle」。
但词有 18254 个,没法一个一个练;音只有几十个,而且**音才是能练的单位**:
fish 和 chip 读错,多半是 /ɪ/ 这一组音的问题,不是两个词的问题。

这里守的是几条不能退化的性质:

1. 归因要**精确**。fish 读成 wish → 差集只有 /f/,不能把 /ɪ/ /ʃ/ 也算上。
2. 归因不到就**不归因**。听到的不是一个词(castle→cassle)时只能说
   「这个词还不稳」,不许硬指某个音。
3. 音素完全一样(two→too)→ 错在重音/语流,不是音素问题。
4. 音素的掌握用**指数移动平均**(先验 0.5),和语法点的「取最好成绩」
   是两套语义:语法点会了就是会了,音素是「稳不稳」。
5. 强度要随时间衰减 —— 半年不练的音确实该再练练。
"""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extensions import phonemes as P            # noqa: E402
from extensions.db import get_db               # noqa: E402


# 假的 CMUdict 片段:够测归因,又不依赖真词库
FAKE_PHONEMES = {
    'fish':   ['F', 'IH', 'SH'],
    'wish':   ['W', 'IH', 'SH'],
    'castle': ['K', 'AE', 'S', 'T', 'AH', 'L'],
    # 注意:'cassle' **故意不在表里** —— 它是「听到的不是一个词」的例子
    'two':    ['T', 'UW'],
    'too':    ['T', 'UW'],
    'little': ['L', 'IH', 'T', 'AH'],
    'litter': ['L', 'IH', 'T', 'ER'],
    'ship':   ['SH', 'IH', 'P'],
    'sheep':  ['SH', 'IH', 'P'],
    # 句子里读对的词 —— 用来验证「读对也记一次 hit」
    'the':    ['DH', 'AH'],
    'prince': ['P', 'R', 'IH', 'N', 'S'],
    'saw':    ['S', 'AO'],
    'a':      ['AH'],
}


@pytest.fixture(autouse=True)
def _seed_kg(tmp_db):
    """播一小撮音素边 + 清空练习记录。

    依赖 tmp_db:不依赖的话,这个 fixture 会写到**生产库** ——
    把孩子真实的音素练习记录抹掉,还会往真词库边上插假数据。
    """
    db = get_db()
    now = int(time.time())
    for word, phs in FAKE_PHONEMES.items():
        for p in phs:
            db.execute(
                'INSERT OR IGNORE INTO kg_node (id, kind, label, level, attrs, updated_at) '
                "VALUES (?, 'phoneme', ?, 1, ?, ?)",
                (f'phoneme:{p}', p, '{"vowel": false, "hint": ""}', now))
            db.execute(
                'INSERT OR IGNORE INTO kg_edge (src, rel, dst, weight, updated_at) '
                "VALUES (?, 'contains', ?, 1.0, ?)",
                (f'word:{word}', f'phoneme:{p}', now))
    db.execute('DELETE FROM kg_phoneme_practice')
    db.commit()
    yield
    db.execute('DELETE FROM kg_phoneme_practice')
    db.commit()


# === 归因 ===

def test_phonemes_for_word():
    assert P.phonemes_for_word('fish') == ['F', 'IH', 'SH']
    assert P.phonemes_for_word('FISH') == ['F', 'IH', 'SH']


def test_phonemes_for_unknown_word_is_empty():
    assert P.phonemes_for_word('zzzznotaword') == []


def test_blame_is_precise_when_both_words_known():
    """fish 读成 wish → 只怪 /f/,不能连累 /ɪ/ /ʃ/。"""
    blamed, precise = P.blame_phonemes('fish', 'wish')
    assert blamed == ['F']
    assert precise is True


def test_blame_falls_back_to_whole_word_when_heard_is_not_a_word():
    """听到的不是一个词(castle→cassle)→ 只能说「这个词还不稳」。"""
    blamed, precise = P.blame_phonemes('castle', 'cassle')
    assert set(blamed) == set(P.phonemes_for_word('castle'))
    assert precise is False


def test_blame_when_phonemes_identical_is_whole_word():
    """two→too 音素一样 → 错在重音/语流,不是音素。"""
    blamed, precise = P.blame_phonemes('two', 'too')
    assert set(blamed) == {'T', 'UW'}
    assert precise is False


def test_blame_for_missed_word_is_whole_word():
    """漏读 → 整个词的音都算可疑。"""
    blamed, precise = P.blame_phonemes('fish', '')
    assert set(blamed) == {'F', 'IH', 'SH'}
    assert precise is False


def test_blame_unknown_word_gives_nothing():
    """没证据就不归因 —— 宁可少说,不要说错。"""
    assert P.blame_phonemes('zzzznotaword', 'fish') == ([], False)


# === 逐词对齐 ===

def test_word_alignment_marks_correct_and_wrong():
    align = P.word_alignment("The little prince saw a fish.",
                             "The litter prince saw a wish.")
    m = {w: err for w, g, err in align}
    assert m['prince'] is False
    assert m['little'] is True
    assert m['fish'] is True
    assert m['the'] is False


def test_word_alignment_marks_missed_word():
    align = P.word_alignment("I saw three ships.", "I saw ships.")
    missed = [(w, g) for w, g, err in align if err]
    assert ('three', None) in missed


# === 记录与状态 ===

def test_missed_word_does_not_blame_phonemes():
    """漏读不算到音素头上。

    whisper 自己就会改写句子(实测把「The little prince saw a fish.」
    转成「little Prince saw a fish.」,开头那个 The 被归一化掉),
    当成「孩子漏读」就会冤枉 /DH/ /AH/。
    孩子没出声也可能是声音小或忘词,跟发音准不准无关。
    """
    P.record_alignment(P.word_alignment("I want three ships.", "I want ships."))
    rows = {r['phoneme_id']: r for r in
            get_db().execute('SELECT * FROM kg_phoneme_practice')}
    # three 的音素不该被记成 miss
    for pid, r in rows.items():
        assert r['misses'] == 0, f'{pid} 被误记成读错'


def test_record_hits_and_misses():
    P.record_alignment(P.word_alignment(
        "The little prince saw a fish.", "The litter prince saw a wish."))
    db = get_db()
    rows = {r['phoneme_id']: r for r in
            db.execute('SELECT * FROM kg_phoneme_practice')}
    # /f/ 读错过 → 强度低
    assert 'phoneme:F' in rows
    assert rows['phoneme:F']['misses'] >= 1
    # /p/ 在 prince 里读对了 → 有 hit
    assert any(r['hits'] > 0 for r in rows.values())


def test_ema_starts_from_prior_and_moves_by_half():
    """第一次观察只走到一半 —— 读对一次不等于「稳了」。"""
    P.record_alignment(P.word_alignment("a fish", "a fish"))
    db = get_db()
    row = db.execute("SELECT strength FROM kg_phoneme_practice "
                      "WHERE phoneme_id = 'phoneme:F'").fetchone()
    # 先验 0.5,观察 1.0 → 0.5*0.5 + 0.5*1.0 = 0.75
    assert row is not None
    assert 0.7 < row['strength'] < 0.8


def test_repeated_success_reaches_mastered():
    for _ in range(4):
        P.record_alignment(P.word_alignment("a fish", "a fish"))
    row = get_db().execute(
        "SELECT strength, hits FROM kg_phoneme_practice "
        "WHERE phoneme_id = 'phoneme:F'").fetchone()
    assert row['strength'] >= 0.85, '读对 4 次还不算稳,EMA 权重有问题'
    assert row['hits'] == 4


def test_repeated_failure_keeps_it_shaky():
    for _ in range(3):
        P.record_alignment(P.word_alignment("a fish", "a wish"))
    row = get_db().execute(
        "SELECT strength, misses FROM kg_phoneme_practice "
        "WHERE phoneme_id = 'phoneme:F'").fetchone()
    assert row['strength'] < 0.4
    assert row['misses'] == 3


def test_counts_accumulate():
    P.record_alignment(P.word_alignment("a fish", "a fish"))
    P.record_alignment(P.word_alignment("a fish", "a fish"))
    row = get_db().execute(
        "SELECT hits, misses FROM kg_phoneme_practice "
        "WHERE phoneme_id = 'phoneme:F'").fetchone()
    assert row['hits'] == 2
    assert row['misses'] == 0


def test_example_word_is_remembered():
    P.record_alignment(P.word_alignment("a fish", "a wish"))
    row = get_db().execute(
        "SELECT example FROM kg_phoneme_practice "
        "WHERE phoneme_id = 'phoneme:F'").fetchone()
    assert row['example'] == 'fish'


def test_shaky_phonemes_lists_only_unstable():
    P.record_alignment(P.word_alignment("a fish", "a wish"))
    shaky = P.shaky_phonemes()
    assert any(p['label'] == 'F' for p in shaky)
    for p in shaky:
        assert p['state'] in ('learning', 'familiar')
        assert p['strength'] < 0.85


def test_stable_phoneme_drops_out_of_the_list():
    for _ in range(4):
        P.record_alignment(P.word_alignment("a fish", "a fish"))
    labels = [p['label'] for p in P.shaky_phonemes()]
    assert 'F' not in labels, '已经稳的音还留在「还不稳」列表里'


def test_decay_makes_long_unpracticed_phoneme_unstable_again():
    """半年不练的音,又该练了。

    注意:判据是「读错过」,所以一个**从没读错**的音不在列表里 ——
    那不是衰减的问题,本来就没它什么事。
    衰减影响的是**读错过、但很久没再练**的那个音的状态:
    它从「基本会了」退回「还得练」,并排到更前面。
    """
    # 先错一次,再连读对 → 状态升到 familiar
    P.record_alignment(P.word_alignment("a fish", "a wish"))
    for _ in range(3):
        P.record_alignment(P.word_alignment("a fish", "a fish"))
    before = next(p for p in P.shaky_phonemes() if p['label'] == 'F')
    # 错一次 + 对三次 → EMA: 0.25 → 0.625 → 0.8125 → 0.906(已稳)
    assert before['state'] == 'mastered', before

    # 把时间戳推到 120 天前
    old_ts = int((time.time() - 120 * 86400) * 1000)
    get_db().execute('UPDATE kg_phoneme_practice SET updated_at = ?', (old_ts,))
    get_db().commit()

    after = next(p for p in P.shaky_phonemes() if p['label'] == 'F')
    assert after['state'] == 'learning', \
        '120 天没练还是记着「基本会了」,音素层就没活起来'
    assert after['strength'] < before['strength']


def test_summary_shape():
    P.record_alignment(P.word_alignment("a fish", "a wish"))
    s = P.summary()
    assert s['shaky'] >= 1
    assert 'counts' in s and 'list' in s


# === 提示 ===

def test_phoneme_tip_is_precise_when_possible():
    from extensions.feedback import _phoneme_tips
    tips = _phoneme_tips(P.word_alignment("a fish", "a wish"))
    assert tips
    assert tips[0]['word'] == 'fish'
    assert tips[0]['precise'] is True
    assert [p['label'] for p in tips[0]['phonemes']] == ['F']


def test_phoneme_tip_not_precise_when_unknown():
    from extensions.feedback import _phoneme_tips
    tips = _phoneme_tips(P.word_alignment("a castle", "a cassle"))
    assert tips
    assert tips[0]['precise'] is False
    assert tips[0]['phonemes']


# === 音素提示语 ===
# 只说「/f/ 还不稳」孩子没法照做,得跟一句怎么发。

def test_phoneme_info_falls_back_to_code_table():
    """图谱里没有这个音素节点时,也要给得出提示语。"""
    db = get_db()
    db.execute("DELETE FROM kg_node WHERE id = 'phoneme:TH'")
    db.commit()
    info = P.phoneme_info('TH')
    assert info['hint'], '图谱缺节点也不能让提示语空掉'
    assert '舌尖' in info['hint']
    assert info['vowel'] is False


def test_phoneme_info_prefers_graph_attrs():
    """图谱里改过提示语,以图谱为准(家长可以在图谱上改)。"""
    db = get_db()
    db.execute(
        "UPDATE kg_node SET attrs = ? WHERE id = 'phoneme:F'",
        ('{"vowel": false, "hint": "我自己写的说明"}',))
    db.commit()
    assert P.phoneme_info('F')['hint'] == '我自己写的说明'


def test_all_consonants_have_actionable_hints():
    """每个辅音都得有一句能照做的说明 —— 这是「可练」的前提。"""
    missing = [p for p in P.CONSONANT_HINTS if not P.CONSONANT_HINTS[p].strip()]
    assert not missing, f'这些辅音没有提示语: {missing}'
    assert len(P.CONSONANT_HINTS) == 24, \
        'ARPAbet 辅音是 24 个(元音 15,共 39),少一个就有一个音说不出怎么发'
    assert len(P.VOWEL_HINTS) == 15, 'ARPAbet 元音是 15 个'
    for ph in ('F', 'TH', 'SH', 'R', 'W', 'L', 'V'):
        assert P.CONSONANT_HINTS[ph].strip(), f'{ph} 没有提示语'


def test_oy_is_a_vowel():
    """OY 是双元音,以前被误标成辅音。"""
    assert 'OY' in P.VOWEL_HINTS
    assert P.phoneme_info('OY')['vowel'] is True


def test_seed_phoneme_hints_fills_empty_and_is_idempotent():
    """回填把空提示补上;再跑一次不改任何东西。"""
    db = get_db()
    db.execute("UPDATE kg_node SET attrs = '{\"vowel\": false, \"hint\": \"\"}' "
               "WHERE id = 'phoneme:F'")
    db.commit()

    n1 = P.seed_phoneme_hints()
    assert n1 >= 1
    assert P.phoneme_info('F')['hint'] == P.CONSONANT_HINTS['F']

    n2 = P.seed_phoneme_hints()
    assert n2 == 0, '回填必须幂等,重复点不能一直改'
    assert P.phoneme_info('F')['hint'] == P.CONSONANT_HINTS['F']


def test_seed_phoneme_hints_does_not_touch_practice_records():
    """回填只改图谱节点,不能顺手清了孩子的练习记录。"""
    P.record_alignment(P.word_alignment("a fish", "a wish"))
    before = get_db().execute(
        "SELECT COUNT(*) FROM kg_phoneme_practice").fetchone()[0]
    assert before > 0
    P.seed_phoneme_hints()
    after = get_db().execute(
        "SELECT COUNT(*) FROM kg_phoneme_practice").fetchone()[0]
    assert after == before
