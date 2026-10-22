# 知识图谱 (KG)

> 一句话:回答「**孩子卡在哪一层**」。
> 不是「这个语法点有多难」,而是「**哪个前置还没会**」。

## 为什么要有它

原来的语法系统是一张平表 —— 24 个语法点(KET 12 + PET 12)平铺在
`web/js/grammar.js` 里。孩子做错一道题,系统只知道「这个点错了」,
家长看到的是「英语不好」,孩子看到的是「我总是做错」。
两边都没有可执行的下一步。

图谱只做一件事:把这 24 个点按**前置依赖**排成有向无环图,
再把单词挂到它需要的语法点上、把音素挂到单词上。
于是「今天该练什么」变成一个能算出来的答案。

## 数据从哪来

| 来源 | 许可 | 提供什么 | 为什么用它 |
|---|---|---|---|
| [ECDICT](https://github.com/skywind3000/ECDICT) | MIT | 音标 / 词性 / 词频(COCA)/ 考纲标签 / 词形变化 | 唯一一个英汉双语、离线、带考纲和词频的开源词库 |
| [CMUdict](https://github.com/cmusphinx/cmudict) | BSD-4-Clause | 单词 → ARPAbet 音素序列(带重音) | 发音权威数据源,跟读反馈直接吃它 |

两个文件都不进仓库(66MB + 3.6MB),跑一次就能拉下来:

```bash
venv/bin/python scripts/build_kg.py --download --limit 30000
```

`--limit` 是「导入 COCA 词频前 N 名」。默认策略是
**高频前 N 名 ∪ 书里真实出现过的所有词** —— 后者才是关键,
那是这个孩子真的在读的东西。

## 建模

三张表,都在 `shadow.db`(见 `extensions/db.py` 的 `SCHEMA`):

```
kg_node(id, kind, label, level, attrs)     -- 节点,id 带类型前缀
kg_edge(src, rel, dst, weight)             -- 边
kg_mastery(node_id, state, strength)       -- 孩子对某个知识点的掌握度
```

节点类型:`word` / `grammar` / `phoneme`
边类型:`requires`(前置) / `contains`(包含) / `derives`(派生) / `practices`(练过)

**为什么用通用表而不是宽表**:音素没有释义,语法没有词频,
塞进一张宽表会得到一堆恒为 NULL 的列。

## 两层图谱,互补不重叠

| 层 | 节点前缀 | 视角 | 来源 |
|---|---|---|---|
| 考试 | `grammar:*` | **KET / PET 考什么** | 本项目自有(24 点,手工前置) |
| 年龄 | `skill:*` | **按年龄该先会什么** | [os-taxonomy](https://github.com/withmarbleapp/os-taxonomy)(119 点,自动导入) |
| 词/音素 | `word:*` `phoneme:*` | 查什么、怎么读 | ECDICT + CMUdict |

两层的差别不是冗余:考试层回答「这场考试会卡我哪里」,
年龄层回答「按课标该教到什么程度」。学校进度和备考进度经常不在一条线上。

### os-taxonomy 这层

- **286 个 English micro-topic**,取语法 75 + 拼读 23 + 词汇 21 = **119 个**
- **192 条前置边**(硬 129 / 软 63),每条带一句 `reason` 人话解释
- 覆盖 4–14 岁,对齐 Common Core / UK National Curriculum,每个点带 `standards` 出处
- 已验证 **English 子图无环**,单测里也守住了

导入:
```bash
venv/bin/python scripts/import_os_taxonomy.py
```

实测它和手工图是互证的:它把 `The Present Perfect Tense` 的前置写成
「Past, Present and Progressive Tense + Subject-verb agreement」——
和我手搓的「现在完成时 ← 一般过去时」结论一致。

> ⚠️ **许可必须遵守**:数据库部分是 **ODbL 1.0**(可商用、需署名,
> 但若再分发这个库本身要保持开放),文本内容是 **CC BY-SA 4.0**。
> 「在产品里使用」没问题;「把这个库单独拿出来发布」就要履行 ODbL。署名:
> Marble Skill Taxonomy (v1) · © Generative Spark, Inc. (Marble) ·
> https://withmarble.com

## 教材 / 考纲 ↔ 图谱的对照(2026-10-20 补)

之前图谱是**悬空**的:24 个点和它们的前置关系都有,但没跟孩子实际在学的
东西连起来。于是「孩子在第 3 单元卡住 → 是哪个前置没会」这条链算不出来。

现在接了两层:

| 层 | 键 | 来源 | 手工? |
|---|---|---|---|
| 教材单元 | `courses.py` 每个单元的 `kg` 字段 | 新概念英语青少版 2A 的 9 个单元 | 手工,跟着内容走 |
| 考试考纲 | `EXAM_SCOPES` | 小托福 TOEFL Junior / 剑桥通用五级 | 手工对照 |

跟读页选了单元之后,标题下面会直接出现:

> 这个单元要会 **现在进行时** · 先要会 一般现在时 · There be 句型

家长页的「知识点顺序」卡多了一个「按考纲看」下拉,选了小托福就是
阅读/听力/口语/写作四个类目,每个类目列出该考的语法点和**缺的前置**。

⚠️ **考纲对照是本项目自己整理的,不是官方考纲原文。** ETS / 剑桥的
官方考纲是版权材料,不能拿我们的对照冒充它。覆盖度说明见下。

## 没有开放数据的部分(实测结论)

- **小托福 / TOEFL Junior**:ETS 官方考纲是版权材料,**没有**开放的结构化
  知识点数据集。国内机构文章把范围讲得很细(句型结构 / 动词时态与语态 /
  从句 / 固定搭配 / 词汇辨析),但那是**转述**,不能当权威数据源。
  好消息是它覆盖的知识点几乎全在那 24 个 KET/PET 点里了(被动语态、
  定语/状语从句、非谓语动词、比较级)。真正缺的是**宾语从句**。
- **小雅思 / 剑桥通用五级**:同理,剑桥考纲版权,无开放数据集。
- **新概念**:GitHub 上能找到按课整理的笔记(`fengjixuchui/NewConceptEnglish`,
  NCE1–NCE4),但那是**笔记不是知识点库**,而且是**成人版 NCE2**,
  和项目在用的**青少版 2A** 是两套教材,不能直接用。

这三块要补只有两条正路:一是拿官方考纲自己整理成 JSON,
二是从**孩子在用的教材课文**里抽——项目里 `courses.py` 的 COURSE_CONTENT
已经是这个思路的雏形。

## 前置边是手工的,不是算的

`extensions/kg.py` 里的 `GRAMMAR_PREREQS` 是手工维护的。

理由:算法能推出「被动语态比现在完成时难」,
但推不出「被动语态**必须先会**现在完成时」——
而这恰恰是家长要的那条边。难度和依赖是两件事。

`tests/test_kg.py` 守住几条结构性不变量:
无环、边不悬空、KET 不会被 PET 反向依赖、深度单调。

## 一条教训:挂错边比不挂更糟

`word → requires → grammar` 这条边,最早是用词典释义去猜的。
结果 `castle`(象棋里的车,英文释义含 "chess can")被判成
「需要情态动词」。

改成只从**这个词所在的那个句子**推之后,还有第二层问题:
`by the castle` 里的 castle 会被算成被动语态(因为句子里有个 by)、
`Tom's dog` 里的 dog 会被算成所有格(因为句子里有个 's)。

现在只认「**匹配片段的字符范围覆盖到这个词本身**」的句型
(`scripts/build_kg.py::_grammar_for_word`),
函数词不建节点,所以 by / 's 这类只沾到旁边实词的句型会自动落空。

结果:边从 5297 条降到 116 条 —— 稀疏,但每一条都站得住。

## 接口

```
GET  /api/kg/stats              图规模
GET  /api/kg/course?course=nc2a 教材每个单元 → 知识点 + 缺的前置
GET  /api/kg/exams              有哪些考纲对照可选
GET  /api/kg/exam/<exam_id>     考纲 → 类目 → 该练的点 + 缺的前置
GET  /api/kg/word/<word>        一个词:音标 / 音素 / 考纲 / 涉及的语法点
GET  /api/kg/path?limit=4       按拓扑深度给出的「下一个该练什么」+ 阻塞它的前置
GET  /api/kg/gaps               前置缺口:谁挡着几个下游
GET  /api/kg/skills?age=10      按年龄取该阶段该会的技能点(带前置与理由)
GET  /api/kg/mastery            每个语法点现在的掌握状态
GET  /api/kg/phonemes           跟读里读错过的音素(带例词)
POST /api/kg/mastery            记一次练习 {items:[{key,correct,total}]}
POST /api/kg/seed               把语法前置图灌进去(幂等)
```

`/path` 和 `/gaps` 已在家长页「🧩 知识点顺序」卡片里可视化。

## 掌握度:图谱的数据源(2026-10-20 接上)

之前 `kg_mastery` 表建好了、`learning_path()` 也会读它,但**没有任何东西往里写** ——
所以「下一个该练什么」一直等于按拓扑深度全量推荐,不是诊断。

现在接上了语法练习的成绩:

```
练习结束 → savePracticeProgress() → POST /api/kg/mastery → kg_mastery 表
```

- 推的是**整份**本地记录,不是只推最后一次 ——
  之前练过的也一并补上,不用为了喂图谱把每个点重练一遍
- 开页面时也会同步一次(所以历史练习立刻生效)
- 语法页的 9 个「教材讲解页」key(present-progressive 这种)通过
  `GRAMMAR_KEY_ALIASES` 记到对应的图谱节点上,不然孩子的练习记录会丢

### 三条规则

1. **取最好成绩,不记最差**。上次 100%、这次 40% 不该被判成「没掌握」。
2. **遗忘靠衰减,不是靠覆盖**。强度按半衰期 45 天衰减(读的时候算,
   表里存的是原始成绩)—— 三个月前会的东西,不该今天还记着「已掌握」。
3. **练过一次就留下记录**,哪怕 0%。「没练过」和「练过但不会」
   给家长的建议完全不同。

状态门槛:≥85% mastered / ≥60% familiar / 其余 learning。

### 反馈闭环

练完给孩子看:「「情态动词」你已经掌握啦」/「基本会了,再练练就更稳」/「还得再练练」。
家长页的「知识点顺序」卡上多一行汇总:**已掌握 N · 在学 N · 要补 N**。

## 音素层:跟读读不准,是不哪个**音**(2026-10-20 接上)

跟读反馈给的是**词级**差异:「你把 castle 读成了 cassle」。
但词有 18254 个,一个一个练是不现实的;**音只有 41 个**,
而且音才是能练的单位 —— fish 和 chip 读错,多半是 /ɪ/ 这一组的问题。

所以把词级差异下沉到音素。CMUdict 的 ARPAbet 音素序列本来就在图谱里
(10 万条 `word → contains → phoneme` 边),直接拿来用。

### 怎么归因

| 期望 | 听到 | 归因 | 精度 |
|---|---|---|---|
| fish (F IH SH) | wish (W IH SH) | **/f/** | 精确 |
| castle | cassle(不是个词) | 整个词的音 | 粗粒度 |
| two (T UW) | too (T UW) | 整个词的音 | 粗粒度(错在重音/语流) |
| fish | (漏读) | 整个词的音 | 粗粒度 |

**归因不到就不归因** —— 说不出是哪个音的时候只说「这个词还不稳」,
不许硬指。粗粒度归因会连带冤枉这个词里本来没问题的音,所以两种要分开标,
界面上也说得清楚。

### 掌握度用 EMA,不是「取最好成绩」

语法点会了就是会了,偶尔做错一套题不代表忘了;
**音素是「稳不稳」**,读对一次也可能只是碰巧。
所以从 0.5(未知)起步,每次观察对半开:

```
1 次读对 → 0.75(基本稳) → 2 次 → 0.875(稳了)
1 次读错 → 0.25(不稳)   → 再读对两次 → 0.66(基本稳)
```

和语法点一样,强度按 45 天半衰期衰减。

### 家长看到什么

「知识点顺序」卡里多一段「发音上还不稳的音(来自跟读)」:

> /F/　 在「fish」里　　读对 0 · 读错 2
> /AH/　 在「little」里　 读对 4 · 读错 2

判据是「**读错过**」,不是「强度低」——
早先按强度过滤,结果读错过的音被后面几次读对稀释掉,反而从列表里消失了。
而那正是家长最该知道的那个音。从没读错过的音不列:41 个全列出来是噪声。

### 孩子看到什么

跟读反馈里多一条:

> 「fish」里的 /f/ 还不稳（上齿轻咬下唇,气从缝里挤出来(像 fish)）

精确归因才给音素;粗粒度只说「这个词的音还不稳 —— 慢慢读几遍」。

括号里那句**怎么发**是必须的。只说「/f/ 还不稳」孩子没法照做,
得给一句对着镜子就能试的说明。所以 24 个辅音每个都配了提示语
(建图脚本早期只给元音写了,26 个辅音是空的 —— 恰恰是辅音最需要)。

提示语有两处来源,图谱优先:

- 图谱节点 `phoneme:F` 的 `attrs.hint`(家长可以在图谱上改)
- 代码里的 `PHONEME_HINTS`(兜底,图谱里没这个节点时也照样有话可说)

回填用 `POST /api/kg/seed`(幂等),只动 `phoneme:*` 节点的 attrs,
不碰词节点、边和任何练习记录。

### 前提

音素数据来自 `scripts/build_kg.py --download` 导入的 CMUdict。
**没跑过这个脚本的库没有音素边**,归因会自动落空(不报错、不影响反馈)。
跟读链路还需要 ASR:`pip install -r requirements-dev.txt`(用 faster-whisper,
不装 torch —— 详见 `docs/ASR.md`)。

接口:`GET /api/kg/phonemes`

## 故事书的章节 → 知识点(2026-10-22 接上)

新概念的单元映射在 `courses.py`(和内容放一起)。
Magic Tree House 的章节映射在 **`extensions/story_kg.py`** ——
单独一个文件,因为章节内容在 `web/js/tutor.js` 里(手抄的正文选段),
映射必须跟内容对着看。用**章节名**做 key,不用序号:
章节增删时序号会错位,名字不会。

### 怎么定的:按正文抽,不按目录名

章节标题("The Invitation""The Golden Hall")**推不出**这章练什么语法 ——
有的标题里根本没有语法信号。所以拿这一章选段里的**每一句**去对,
句子里出现了这个结构、且读这章的孩子要能读懂它,才算这个知识点。

判据三条:

1. 句子里**出现了**这个结构(不是「这章大概涉及」);
2. 这个结构**挡住理解**了(读不懂这一句就读不下去);
3. 出现 2 次以上,或者它本身就是这一章的主干句式。

反面例子(特意没算进去):代词。7 章里章章都有,放进「这一章要会」
里没有信息量。

每条映射后面都附了**例句**(`story_kg.py` 的注释里),
方便以后核对:翻到那句话,孩子得能读出来 —— 这才是「要会」的依据。

| 章节 | 要会 | 例句 |
|---|---|---|
| 1 The Invitation | 过去完成时 · 现在进行时 · 祈使句 · 动名词/不定式 | Sunlight **had faded**… / clouds **were moving** in / **Wait. Look.** / a bird **sitting** on a branch |
| 2 Camelot | 过去完成时 · 现在进行时 · 情态动词 · 动名词/不定式 | the tree house **had landed** / Annie **was staring** / He **could** see / towers, **sounding** sad |
| 4 The Christmas Knight | There be · 现在完成时 · 情态动词 · 动名词/不定式 | **There is** no feast / the darkest castle **I've ever seen** / We **must** find / **to protect** the king |
| 7 The Magic Spell | 现在完成时 · 情态动词 · 动名词/不定式 · 名词所有格 | the evil knight **has put** a spell / kindness **can** break this / **to break** the spell / **Jack's** hand |
| 13 The Golden Hall | 被动语态 · 现在完成时 · 现在进行时 · 动名词/不定式 | the hall **was filled with** light / the Christmas **I've been dreaming of** / **were feasting** / **began to spin** |
| 14 Home | 现在进行时 · 情态动词 · 祈使句 · 动名词/不定式 | the snow **was falling** softly / we **could** go back / **Let's** write / too magical **to forget** |
| 16 The End | 形容词比较级 · 情态动词 · 名词所有格 · 频率表达 | the **best** Christmas ever / the gift **would stay** / **Morgan's** gift / **ever** |

跟读页上,选中章节就能看到:

> 这一章要会 过去完成时 · 现在进行时 · 祈使句 · 动名词/不定式
> · 先要会 现在完成时 · 一般现在时 · There be 句型 · 情态动词

「先要会」来自 `GRAMMAR_PREREQS`,和教材那条路是同一套前置边。

### 为什么单独一个文件

`courses.py` 的单元映射是**教材的事实**(改教材时顺手改);
故事书的映射是**这批选段的性质** —— 换一批选段就得重判,
和教材表不是一回事。混在一起会让人以为「改了个章节名就等于改了教材」。

接口:`GET /api/kg/course?course=mth29`
测试:`tests/test_story_kg.py` —— 守三件事:章节名和 `tutor.js` 对得上、
**顺序**对得上(前端是按序号取 API 的 units 的,顺序错了会显示
隔壁那章的知识点而且不报错)、每个 key 都真在图谱里。

## 还没做的

- 教材对照目前只覆盖新概念青少版 2A 的 9 个单元。
  Magic Tree House 那本书的**全书 21 章**还没映射 ——
  现在只映射了跟读页手抄的 7 章选段。
  其余章节要么补选段,要么直接从全书正文抽(全书正文在 `books` 表里)。
- 音素层目前只有**跟读**一个数据源。语法练习该反映的是「会不会用」,
  不该混进「读得准不准」—— 所以两类数据是分开的,没混。
- 跟读页的「发音评分」还只有转写 + 词级差异 + 音素归因,
  没有音高/节奏维度的评分(那个要更重的模型,现在不值当)。
- `derives` 边(时态/单复数 → 原形)的数据 ECDICT 已经给了,
  存在 `attrs.forms` 里,没建成边。
