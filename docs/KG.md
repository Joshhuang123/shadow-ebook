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
POST /api/kg/seed               把语法前置图灌进去(幂等)
```

`/path` 和 `/gaps` 已在家长页「🧩 知识点顺序」卡片里可视化。

## 还没做的

- `kg_mastery` 表建好了但**还没接数据源** —— 现在所有语法点的状态都是
  「未掌握」,所以 `/api/kg/path` 等于按拓扑深度全量推荐。
  接上语法测验的正确率之后,「下一个该练什么」才会真正个性化。
  **这是让图谱从「静态地图」变成「活的诊断」的关键一步,下一步做它。**
- 教材对照目前只覆盖新概念青少版 2A 的 9 个单元。
  Magic Tree House 那本书的章节还没映射到知识点 ——
  它是故事书,知识点要从正文里抽,不是从目录名。
- 音素层只有 `phoneme` 节点和提示文案,还没接跟读页的
  发音评分( whisper 那条链路 )。
- `derives` 边(时态/单复数 → 原形)的数据 ECDICT 已经给了,
  存在 `attrs.forms` 里,没建成边。
