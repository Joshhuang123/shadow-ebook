"""Magic Tree House 的章节 → 知识点。

为什么单独一个文件
------------------
新概念的映射在 `courses.py` 里(和内容放在一起,改教材时顺手改)。
Magic Tree House 的章节内容在 `web/js/tutor.js` 里(手抄的正文选段),
而映射必须跟内容对着看,所以单独放这里,用**章节名**做 key
(不是序号 —— 章节增删时序号会错位,名字不会)。

怎么定的(2026-10-22)
--------------------
**按正文抽,不按目录名。** 章节标题("The Invitation""The Golden Hall")
推不出「这章练什么语法」—— 有的章节标题里根本没有语法信号。
所以拿这一章选段里的**每一句**去对,句子里出现了这个结构、
且读这章的孩子要能读懂它,才算这个知识点。

每个映射后面都附了例句,方便以后核对:
翻到那句话,孩子得能读出来 —— 这才是「要会」的依据。

「要会」的判据
--------------
1. 句子里**出现了**这个结构(不是「这章大概涉及」);
2. 这个结构**挡住理解**了(孩子读不懂这一句就读不下去);
3. 出现 2 次以上,或者它本身就是这一章的主干句式。

反面例子(特意没算进去):
- "Jack shivered." → 一般过去时?算,但每章都是过去时,没有区分度,
  真正有区分度的是 had faded / had landed 这种**过去完成时**。
- "He and Annie were walking home" → 代词? 代词太基础,7 章都有,
  放进「这个单元要会」里没有信息量。
"""
from extensions.kg import GRAMMAR_NODES

# 章节名 → 知识点 key 列表(顺序 = 重要程度)
MTH_CHAPTER_KG = {
    "Chapter 1: The Invitation": [
        # "Sunlight had faded from the late-afternoon sky."
        #   → had + p.p.,这一章的时态骨架
        "pet-past-perfect",
        # "Puffy snow clouds were moving in." / "He and Annie were walking home"
        "ket-present-continuous",
        # "Wait. Look." / "Come on!"
        "ket-imperative",
        # "She pointed to a white bird sitting on a bare tree branch."
        "pet-gerund-infinitive",
    ],
    "Chapter 2: Camelot": [
        # "The tree house had landed in a grove of tall, bare trees."
        "pet-past-perfect",
        # "Annie was staring out the window." / "A woman was crossing the drawbridge."
        "ket-present-continuous",
        # "He could see his breath in the dim light." / "I hope we came..."
        "ket-modals",
        # "Wind whistled through its tall towers, sounding sad and lonely."
        "pet-gerund-infinitive",
    ],
    "Chapter 4: The Christmas Knight": [
        # "There is no feast tonight." / "Something is very wrong in Camelot."
        "ket-there-be",
        # "This is the darkest castle I've ever seen." / "I have come to see..."
        "pet-present-perfect",
        # "We must find the source of the darkness." / "is supposed to be"
        "ket-modals",
        # "We are here to protect the king and queen!"
        "pet-gerund-infinitive",
    ],
    "Chapter 7: The Magic Spell": [
        # "The evil knight has put a spell on King Arthur."
        "pet-present-perfect",
        # "Only true kindness can break this curse." / "We must find..."
        "ket-modals",
        # "I need your help to break the spell." / "began to glow"
        "pet-gerund-infinitive",
        # "Annie reached for Jack's hand."
        "ket-possessive",
    ],
    "Chapter 13: The Golden Hall": [
        # "The great hall was filled with light and warmth."
        "pet-passive",
        # "This is the Christmas I've been dreaming of!" / "You have earned..."
        "pet-present-perfect",
        # "Knights and ladies were feasting and singing."
        "ket-present-continuous",
        # "The tree house began to spin slowly." / "It was time to go home."
        "pet-gerund-infinitive",
    ],
    "Chapter 14: Home": [
        # "The snow was falling softly outside."
        "ket-present-continuous",
        # "I wish we could go back someday."
        "ket-modals",
        # "Let's write about our adventure."
        "ket-imperative",
        # "Some things are too magical to forget."
        "pet-gerund-infinitive",
    ],
    "Chapter 16: The End": [
        # "That was the best Christmas ever." / "the strongest of all"
        "ket-comparatives",
        # "Morgan's gift would stay with them forever."
        "ket-modals",
        # "Morgan's gift"
        "ket-possessive",
        # "the best Christmas ever"
        "ket-frequency",
    ],
}

# 一句话的备注,给家长页/文档看:这章在故事里干什么用的
MTH_CHAPTER_NOTE = {
    "Chapter 1: The Invitation": "收到邀请,雪夜赶回家 —— 全章是过去的动作叠着进行时",
    "Chapter 2: Camelot": "落到卡米洛特,眼前是一座死城 —— 描写为主,感官动词多",
    "Chapter 4: The Christmas Knight": "圣诞骑士登场,说城里出事了 —— 说话多,转折多",
    "Chapter 7: The Magic Spell": "梅林现身,合力破咒 —— 情态和不定式最密",
    "Chapter 13: The Golden Hall": "大厅重开,骑士宴饮 —— 被动和完成时最密",
    "Chapter 14: Home": "回家,雪还在下 —— 抒情,祈使和 wish 多",
    "Chapter 16: The End": "结尾一段话,总结 —— 比较级和 ever 这类收尾词多",
}


def story_units(course_id: str) -> list:
    """故事书(Magic Tree House)的章节 → 图谱单元。"""
    if course_id != 'mth29':
        return []
    out = []
    for i, (name, keys) in enumerate(MTH_CHAPTER_KG.items()):
        valid = [k for k in keys if k in GRAMMAR_NODES]
        out.append({
            'index': i,
            'name': name,
            'note': MTH_CHAPTER_NOTE.get(name, ''),
            'grammar': [
                {'key': k, 'label': GRAMMAR_NODES[k][0], 'level': GRAMMAR_NODES[k][1]}
                for k in valid
            ],
        })
    return out
