# 📖 Shadow Ebook - 英语电子书阅读与跟读学习

免费开源的英语电子书阅读器，支持 EPUB 导入、点击查词、TTS 朗读、蓝思值计算，专为英语学习者设计。

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

## ✨ 功能特点

### 📖 电子书阅读
- **EPUB 导入** - 一键导入任意 EPUB 电子书
- **点击查词** - 点击任意单词，即时显示中英文释义
- **生词本** - 自动累计，浏览器本地保存
- **AR/ATOS 值** - 实时计算阅读等级
- **TTS 朗读** - 点击句子自动朗读（Microsoft edge-tts）

### 🗣️ 跟读学习
- **句子朗读** - 点击句子自动播放，发音清晰自然
- **跟读练习** - 录音对比，提升口语
- **理解题测试** - 检验阅读理解

### 📚 内置内容
- 新概念英语青少版 2A 课程
- Magic Tree House #29: Christmas in Camelot
- Harry Potter #1: Philosopher's Stone

### 🎓 语法学习
- **KET (A2)** - 一般现在时、现在进行时、一般过去时、There be句型、be going to、情态动词、形容词比较级、频率表达、名词所有格、代词系统、介词用法、祈使句
- **PET (B1)** - 现在完成时、过去完成时、被动语态、条件句、间接引语、定语从句、情态动词完成时、used to、动名词/不定式、数量词、状语从句、并列连词
- 新概念英语青少版 2A 核心语法

## 🚀 快速开始

### 安装依赖

```bash
pip install flask edge-tts
```

### 运行

```bash
python tutor_web.py
```

然后打开浏览器访问：**http://localhost:5002**

### 使用电子书

1. 打开 http://localhost:5002/ebook
2. 点击 **➕ 导入新书** 选择 EPUB 文件
3. 选择章节，点击任意句子开始朗读
4. 点击单词查词，自动累计生词

## 📁 项目结构

```
shadow-learning/
├── tutor_web.py          # Flask 服务器 (入口)
├── web/
│   ├── ebook.html        # 电子书阅读器
│   ├── tutor.html        # 跟读辅导界面
│   └── grammar_present_tenses.html  # 语法学习
├── data/
│   ├── books/            # 电子书 JSON 文件
│   └── grammar/          # 语法资料
└── audio/
    └── tts/              # TTS 缓存音频
```

## 🛠️ 技术栈

| 功能 | 技术方案 |
|------|----------|
| Web 服务器 | Flask (Python) |
| 前端 | 原生 HTML/CSS/JS |
| 语音合成 | Microsoft edge-tts (免费) |
| 词典 API | dictionaryapi.dev + MyMemory |
| 发音评分 | Web Speech API |

## 📝 License

MIT License - 免费商用、学习、修改

## 🙏 鸣谢

本项目参考了以下优秀资源：

- **[interaminense/learning-english](https://github.com/interaminense/learning-english)** - 英语学习综合资源库，整合了丰富的听说读写全阶段学习资源
