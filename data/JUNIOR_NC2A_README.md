# 新概念英语青少版2A - 学习内容说明

## 已添加内容

### 1. 语法模式 (agents/grammar_agent.py)
已在 GrammarAgent 中添加以下核心语法模式：

#### Unit 1-2: 现在进行时 (Present Progressive)
- `\b(am|is|are) \w+ing\b` - 现在进行时基本结构
- 否定句和疑问句变化

#### Unit 5-6, 10: 一般现在时 (Simple Present)
- 第三人称单数变化规则
- 频率副词和时间表达

#### Unit 11-13: 一般过去时 (Simple Past)
- was/were 用法
- 规则动词 -ed 变化
- 不规则动词过去式 (went, saw, ate, had...)
- 过去时疑问句

#### 其他语法点
- Unit 3: 名词性物主代词 (mine, yours, his, hers...)
- Unit 4: 祈使句 (Open..., Don't...)
- Unit 7: 频率表达 (once, twice, How often...?)
- Unit 8: be going to 表计划
- Unit 9: want to do / want sb to do

### 2. 词汇文件 (data/words/junior_new_concept_2a.json)
包含 8 个单元的核心词汇，每个词条包含：
- 单词
- 音标
- 中文意思
- 例句

### 3. 语法速查卡 (data/grammar/junior_nc2a_grammar.md)
三时态对比表、不规则动词表、句型结构速查

## 使用建议

1. **影子跟读练习**: 使用新概念教材音频进行跟读
2. **语法分析**: 读句子时 GrammarAgent 会自动识别时态
3. **词汇积累**: 定期复习 junior_nc2a.json 中的词汇
4. **错题整理**: 练习册中的错题可自动整理到错题本

## 文件位置
- 语法模式: `agents/grammar_agent.py`
- 词汇表: `data/words/junior_new_concept_2a.json`
- 语法速查: `data/grammar/junior_nc2a_grammar.md`
