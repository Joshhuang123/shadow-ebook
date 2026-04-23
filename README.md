# 📖 Shadow Ebook - 英语电子书阅读与跟读学习

免费开源的英语电子书阅读器，支持 EPUB 导入、点击查词、TTS 朗读、蓝思值计算，专为英语学习者设计。

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

## ✨ 功能特点

### 📖 电子书阅读
- **EPUB 导入** - 一键导入任意 EPUB 电子书
- **点击查词** - 点击任意单词，即时显示中英文释义
- **艾宾浩斯复习** - 科学间隔复习，记单词更高效
- **AR/ATOS 值** - 实时计算阅读等级
- **TTS 朗读** - 点击句子自动朗读（Microsoft edge-tts）
- **章节理解测验** - 读完章节做理解题测试

### 🗣️ 跟读学习
- **句子朗读** - 点击句子自动播放，发音清晰自然
- **发音波形对比** - 录音后直观对比原音与录音的波形差异
- **跟读练习** - 录音对比，提升口语
- **理解题测试** - 检验阅读理解

### 📊 学习统计
- **连续打卡天数** - 记录每日学习习惯
- **学习时长统计** - 近7天学习时长柱状图
- **词汇量测试** - 20题测试评估词汇水平
- **个性化书单推荐** - 根据词汇水平推荐合适书籍

### 📚 内置内容
- 新概念英语青少版 2A 课程
- Magic Tree House #29: Christmas in Camelot
- Harry Potter #1: Philosopher's Stone

### 🎓 语法学习
- **KET (A2)** - 一般现在时、现在进行时、一般过去时、There be句型、be going to、情态动词、形容词比较级、频率表达、名词所有格、代词系统、介词用法、祈使句
- **PET (B1)** - 现在完成时、过去完成时、被动语态、条件句、间接引语、定语从句、情态动词完成时、used to、动名词/不定式、数量词、状语从句、并列连词
- 新概念英语青少版 2A 核心语法

### 📱 PWA 离线支持
- 可安装到桌面/主屏幕
- 断网仍可浏览已缓存内容

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

### 页面导航

| 页面 | 路径 | 功能 |
|------|------|------|
| 电子书 | `/` 或 `/ebook` | 阅读电子书、查词、生词本 |
| 跟读学习 | `/tutor` | 跟读练习、波形对比 |
| 语法学习 | `/grammar` | KET/PET 语法讲解与练习 |
| 学习统计 | `/stats` | 打卡、时长、词汇测试、书单推荐 |

### 使用电子书

1. 打开 http://localhost:5002/ebook
2. 点击 **➕ 导入新书** 选择 EPUB 文件
3. 选择章节，点击任意句子开始朗读
4. 点击单词查词，自动累计生词
5. 点击 **📖 章节测验** 做理解题

## 📁 项目结构

```
shadow-learning/
├── tutor_web.py          # Flask 服务器 (入口)
├── web/
│   ├── ebook.html        # 电子书阅读器
│   ├── tutor.html        # 跟读辅导界面
│   ├── grammar.html      # 语法学习
│   ├── stats.html        # 学习统计
│   ├── manifest.json     # PWA 配置
│   └── service-worker.js # 离线支持
├── data/
│   └── books/            # 电子书 JSON 文件
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
| 离线支持 | Service Worker |

## 📝 License

MIT License - 免费商用、学习、修改

## 🙏 鸣谢

本项目参考了以下优秀资源：

- **[interaminense/learning-english](https://github.com/interaminense/learning-english)** - 英语学习综合资源库，整合了丰富的听说读写全阶段学习资源
