# 📖 Shadow Ebook - 英语电子书阅读与跟读学习

免费开源的英语电子书阅读器，支持 EPUB 导入、点击查词、TTS 朗读、蓝思值计算，专为英语学习者设计。配套语法学习、跟读练习、词汇复习、家长监控。

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

---

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

### 👨‍👩‍👧 家长监控
- **学习时长统计** - 总时长、最近 7 天、连续打卡
- **掌握进度** - 词汇、语法、跟读分项进度
- **重置/清空数据** - 一键重置孩子的学习记录

### 📱 PWA 离线支持
- 可安装到桌面/主屏幕
- 断网仍可浏览已缓存内容

---

## 🚀 快速开始

### 硬件要求

| 设备 | 用途 | 说明 |
|------|------|------|
| 老师电脑 / 服务器 | 运行服务 | Mac/Windows/Linux，需联网（TTS 走云端） |
| 学生平板 / 电脑 | 学习客户端 | iPad / Android 平板 / 笔记本，浏览器访问 |
| 路由器 | 同 WiFi | 平板和电脑需在同一局域网 |

> 平板无需安装 edge-tts，语音由电脑生成后推送过去。

### 安装依赖

#### Mac / Linux

```bash
# 克隆项目
git clone https://github.com/你的用户名/shadow-learning.git
cd shadow-learning

# 创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate
pip install flask edge-tts
```

#### Windows

```powershell
py -m venv venv
venv\Scripts\activate
pip install flask edge-tts
```

### 启动服务

#### 一键启动（Mac / Linux）

```bash
./start_lan.sh          # HTTP，局域网可访问
./start_https.sh        # HTTPS（iOS Safari 跟读需要 HTTPS 权限麦克风）
```

#### 手动启动

```bash
source venv/bin/activate
python3 app.py
```

启动后显示：
```
🦊 Shadow Learning
======================================
🌐 本机访问: http://localhost:5002
📱 局域网访问: http://192.168.x.x:5002
```

> **iOS Safari 提示**：跟读功能需要麦克风权限，仅在 HTTPS 站点下浏览器才会授权。本机请用 `./start_https.sh`（首次会生成自签名证书）。详细 HTTPS 配置见 `certs/README.md`（如果有的话）或直接用 mkcert：`./scripts/gen_https_cert.sh`。

---

## 📱 局域网访问

服务器运行后，其他设备也可访问，实现 **同一局域网共享 TTS 语音**。

**查找本机 IP：**
- Mac / Linux: `ifconfig | grep "inet " | grep -v 127.0.0.1`
- Windows: `ipconfig`

**手机 / 平板访问：**
1. 确保设备和电脑连着同一个 WiFi
2. 浏览器打开 `http://电脑IP:5002`
3. 例如电脑 IP 是 `192.168.1.100`，平板就打开 `http://192.168.1.100:5002`

### 安装到 iPad / Android 平板

专为孩子设计，平板适配优化：
- **大按钮** - 便于小手点击
- **触摸优化** - 滑动翻页、点击查词
- **离线可用** - 安装后没网也能用

**安装步骤：**
1. 用平板浏览器打开 `http://电脑IP:5002`
2. 点击浏览器分享按钮
3. 选择 "添加到主屏幕" 或 "安装应用"
4. 之后直接从桌面图标打开即可

---

## 🧭 页面导航

| 页面 | 路径 | 功能 |
|------|------|------|
| 电子书 | `/` 或 `/ebook` | 阅读电子书、查词、生词本 |
| 跟读学习 | `/tutor` | 跟读练习、波形对比 |
| 语法学习 | `/grammar` | KET/PET 语法讲解与练习 |
| 学习统计 | `/stats` | 打卡、时长、词汇测试、书单推荐 |
| 家长监控 | `/parent` | 学习时长、掌握进度、清除数据 |

---

## 📖 使用说明

### 电子书阅读

1. 打开 http://localhost:5002/ebook
2. 点击 **➕ 导入新书** 选择 EPUB 文件
3. 选择章节，点击任意句子开始朗读
4. 点击单词查词，自动累计生词
5. 点击 **📖 章节测验** 做理解题

### 跟读练习

1. 进入 `/tutor`，选择学习内容（新概念 / Magic Tree House）
2. 点击 **🔊 听标准发音** 听原音
3. 点击 **🎤 开始跟读** 录音
4. 听自己的录音，对比波形
5. 完成所有句子后做理解测验

### 生词复习（艾宾浩斯）

1. 阅读时点击不认识的单词
2. 点击 **+ 生词本** 收藏
3. 第二天回来，系统会提醒复习
4. 复习后根据记忆曲线自动安排下次复习时间

### 添加新书

1. 打开 **电子书** 页面
2. 点击 **导入 EPUB** 按钮
3. 选择本地 EPUB 文件
4. 等待解析完成（约10秒）
5. 新书出现在书架上

---

## 📚 推荐书单（蓝思值参考）

| 书名 | 蓝思值 | 适合年级 | 兴趣分类 |
|------|--------|----------|----------|
| Magic Tree House 系列 | 450-600L | 3-4 年级 | 冒险 |
| Percy Jackson 系列 | 590-650L | 5-6 年级 | 奇幻 / 神话 |
| Diary of a Wimpy Kid | 800L | 4-5 年级 | 校园 / 幽默 |
| Harry Potter #1 | 880L | 6 年级以上 | 奇幻 |
| Christmas in Camelot | 500L | 3-4 年级 | 冒险（节日） |

> 已默认导入 Magic Tree House #29、Percy Jackson: Lightning Thief、Harry Potter #1，可直接用。

---

## ❓ 常见问题 FAQ

### Q: 平板上无法录音？
**A:** 检查平板浏览器是否授予了 **麦克风权限**。首次使用会弹出授权提示，请点击允许。
- iOS Safari：跟读必须在 HTTPS 站点下才能授权，请用 `./start_https.sh` 启动并信任自签名证书。
- Android Chrome：通常 `http://` 也可以授权。

### Q: 学生打不开页面？
**A:**
1. 确认平板和老师在同一个 WiFi
2. 确认老师电脑的服务还在运行（终端不要关闭）
3. 电脑的防火墙没有阻止 5002 端口
4. 尝试刷新页面或重启浏览器

### Q: 提示"无法访问麦克风"？
**A:** iOS Safari 需要用户主动点击录音按钮才会请求权限，不要让平板进入锁屏状态。

### Q: 声音播放有延迟？
**A:** 首次使用需要联网下载语音库（edge-tts 调用云端），之后会缓存到本地 `audio/tts/`。缓存目录有 2GB LRU 自动清理。

### Q: 数据会丢失吗？
**A:** 数据保存在浏览器 `localStorage`，清浏览器缓存会丢。家长可在 `/parent` 页面查看统计；老师建议每学期让学生截图保存或导出。

### Q: 需要 Python 几？
**A:** 3.11+。edge-tts 6.x+ 兼容。

### Q: 必须用 edge-tts 吗？
**A:** 不用。可以在 `extensions/tts.py` 顶部的 `VOICES` 列表改其它引擎/嗓音。但当前所有功能（缓存在 `audio/tts/`）都按 edge-tts 写。

### Q: 平板需要装什么？
**A:** 浏览器即可。推荐 Safari（iOS）或 Chrome（Android）。

---

## 📁 项目结构

```
shadow-learning/
├── app.py                  # Flask 入口 (HTML 页面路由 + extensions 注册)
├── extensions/             # 按域拆分的业务模块
│   ├── auth.py             # 家长 PIN 鉴权 + 登录/接口限流
│   ├── books.py            # 书籍 CRUD + EPUB 解析 + 路径穿越防御
│   ├── courses.py          # 课程内容 + 理解题
│   ├── db.py               # SQLite 连接 + schema + 首启 JSON→DB 迁移
│   ├── parent_data.py      # 家长统计/词汇/设置 CRUD + PIN 改密 + 导出
│   ├── pwa.py              # PWA 壳 (theme.js / sync.js / manifest / SW)
│   └── tts.py              # edge-tts 朗读 + LRU 缓存 + 预生成后台线程
├── web/
│   ├── ebook.html          # 电子书阅读器
│   ├── tutor.html          # 跟读辅导界面
│   ├── grammar.html        # 语法学习
│   ├── stats.html          # 学习统计
│   ├── parent.html         # 家长仪表盘
│   ├── theme.js            # 日/夜主题 token
│   ├── sync.js             # 数据上报
│   ├── a11y.js             # 模态框焦点陷阱
│   ├── manifest.json       # PWA 配置
│   ├── service-worker.js   # 离线缓存
│   └── kid-touch.css       # 触摸优化样式
├── android/                # Capacitor Android 壳工程（npm run sync 后可编译 APK）
├── capacitor.config.json   # Capacitor 配置（webDir=web）
├── package.json            # npm 依赖（@capacitor/core/cli/android）
├── scripts/
│   └── gen_https_cert.sh   # 自签名 HTTPS 证书生成
├── certs/                  # HTTPS 证书（已 gitignore）
├── tests/                  # 3 个 guard test (safe_book_path / check_pin / evict_tts)
├── data/
│   ├── shadow.db           # SQLite (books / parent_data / parent_pin),首启生成
│   ├── shadow.log          # INFO 日志(gitignore)
│   └── covers/             # 书籍封面图
└── audio/
    └── tts/                # TTS 缓存音频（LRU 自动清理)
```

---

## 📦 打包为 Android App

项目已经配置好 Capacitor 壳工程，可以打包成 Android APK / AAB 发到平板上离线使用。

**前置条件**：本机装了 Node.js 18+ 和 Android Studio（首次构建会下载 Gradle + Android SDK）。

**构建步骤：**

```bash
# 1. 安装 npm 依赖（仅首次或 Capacitor 升级时）
npm install

# 2. 把 web/ 同步到 android/app/src/main/assets/public/
#    注意：android/app/src/main/assets/public/ 已经在 android/.gitignore 里被排除，
#    不要手动 commit 这个目录。
npx cap sync android

# 3. 在 Android Studio 中打开 android/ 目录构建 APK：
#    - Open → 选择 android/
#    - 等 Gradle sync 完 → Build → Build Bundle(s) / APK(s) → Build APK(s)
#    - APK 输出在 android/app/build/outputs/apk/debug/
#
# 或者用命令行：
cd android && ./gradlew assembleDebug
```

> **更新 web 后的重新打包**：改完 `web/` 里的文件，跑一次 `npx cap sync android`，然后重新构建 APK。`web/fonts/` 字体文件会跟着一起打包进 APK，离线可用。

---

## 🛠️ 技术栈

| 功能 | 技术方案 |
|------|----------|
| Web 服务器 | Flask (Python) |
| 前端 | 原生 HTML / CSS / JS |
| 语音合成 | Microsoft edge-tts (免费) |
| 词典 API | dictionaryapi.dev + MyMemory |
| 发音评分 | Web Speech API |
| 离线支持 | Service Worker (PWA) |
| 主题系统 | CSS `:root` + theme.js 日/夜循环 |
| Android 壳 | Capacitor |

---

## 🔒 安全说明

- **家长监控** (`/parent`) 用 PIN 码保护，PIN 以 SHA-256 哈希存储，不存明文
- **会话 Cookie** 标记 `HttpOnly + SameSite=Lax`，不可被前端 JS 读取
- **登录限流**：5 次错误后锁定 60 秒
- **路径遍历防护**：所有 EPUB 导入、书籍读取都校验 book_id 格式
- **录音/跟读** 仅在用户主动点击时请求麦克风权限

⚠️ **本服务默认监听 `0.0.0.0:5002`（局域网可访问）**。如需在公网部署，请务必：
1. 改成 HTTPS（`./start_https.sh` 或反向代理 nginx + Let's Encrypt）
2. 改 `app.secret_key`（现在是 dev 默认值，**生产必改**）
3. 加防火墙白名单

---

## 📝 License

MIT License - 免费商用、学习、修改

## 🙏 鸣谢

本项目参考了以下优秀资源：

- **[interaminense/learning-english](https://github.com/interaminense/learning-english)** - 英语学习综合资源库，整合了丰富的听说读写全阶段学习资源
