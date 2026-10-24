# 推广素材(2026-10-22 / 10-24 / 10-25)

给 X / 小红书 / 抖音 / 视频号用的图文与短视频。

**素材里的截图都是这个项目的真实运行界面**(本机局域网实例),
用的是项目自己的字体和纸面色 —— 推出去的东西和打开的东西是同一套。
家长页那组数字是为截图灌的**演示数据**(隔离实例,不含任何真实孩子记录)。

## 目录(按 josh-media skill 的交付契约排)

```
promo/
├── 成品/           成片 mp4(竖版 9x16 + 横版 16x9)
├── 封面/           封面投放包:四画幅 × 三档 = 12 张 + 可保存的那一屏
├── 文案/           互动层文案.md(三平台标题/简介/首评/置顶/话题/节奏)
├── cards/          图文卡片 12 张(小红书 3:4 + X 16:9)
├── scripts/        生成脚本
├── POSTS.md        图文版发布文案(更长,适合公众号/长贴)
├── COPY.md         另一版文案
└── README.md
```

`python3 ~/.minimax/skills/josh-media/scripts/gate.py promo` → 交付门禁
(标题字数 + 禁忌词 + 三平台简介 + 封面四画幅齐不齐 + 角标与成片时长一致)。

## 视频:沉稳高管 TTS + 烧进画面的字幕

- **音色**:`Chinese (Mandarin)_Reliable_Executive`(沉稳高管),全系列一个音色不换
- 旁白用 MiniMax TTS **逐句**合成 → 用每句真实时长重建时间轴
  (句间静音 0.30s、场间 0.75s、片尾 2.75s),字幕跟着句子的 start/end 走
- 响度归一到 **-16 LUFS**
- 没有背景音乐(留白方便自己配,也免版权问题)

| 段 | 内容 |
|---|---|
| 钩子(前 3 秒) | 「孩子的英语录音,不上传云端。」—— 反常识 + 后果型。**不塞关注引导** |
| 是什么 | 家里一台电脑就够,平板打开浏览器就能用 |
| 像书 | 纸的排版、点词查释义、一句一句地走 |
| 跟读 | 不说「词错了」,说「这个 o 的音还不稳」 |
| 图谱 | 教材、考纲、掌握度画在一张图上 |
| 家长页 | 诊断不是报表 |
| 收尾 | 不用云端 + 预告一次互动题 |

## 封面投放包(四画幅 × 三档)

| 画幅 | 尺寸 | 用在哪 |
|---|---|---|
| 竖 9:16 | 1080×1920 | 抖音主封面 / 全屏播放页 |
| 竖 3:4 | 1080×1440 | 抖音信息流、搜索结果位(主用) |
| 横 4:3 | 1440×1080 | 横屏入口、视频号、小红书(主用) |
| 横 16:9 | 1920×1080 | 横屏主播放位、B 站 |

每画幅三档:标准 / 高清(2×) / 小图(列表缩略)。

**四个画幅各自排版,不是同一版裁切**:竖版堆叠(眉标→主视觉→标题→
部署名→角标),横版并置(眉标左上→文字左→主视觉右→部署名→角标右下)。
时长角标用 **ffprobe 实测值**,不是估算。

`封面/可保存的那一屏.png`:12 个最容易读错的音的嘴型表 —— 片尾的收藏钩子,
内容与视频里「/AO/ 还不稳」用的是同一套提示语。

## 怎么重新生成

```bash
cd ~/shadow-learning
./start_lan.sh                                   # 素材来自真实界面
python3 promo/scripts/capture.py                 # 1) 拍真实界面 → promo/shots/
python3 promo/scripts/cards.py                   # 2) 出卡片(竖版)
python3 promo/scripts/cards.py --landscape
python3 promo/scripts/tts_minimax.py             # 3) 逐句合成旁白 → timeline.json
python3 promo/scripts/video_mm.py 9x16           # 4) 渲染 + 合成
python3 promo/scripts/video_mm.py 16x9
python3 promo/scripts/covers.py                  # 5) 封面投放包(12 张)
python3 promo/scripts/save_screen.py             # 6) 可保存的那一屏
```

依赖:无头 Chrome(截图/渲染)+ ffmpeg(合成)+ `mcode-tools`(MiniMax TTS)。
Python 只用标准库 —— 截图走自带的 CDP 驱动(`scripts/cdp.py`)。

**口播稿改了要重跑字数实算**,不许目测:

```bash
node ~/.minimax/skills/josh-media/scripts/wordcount.js 口播稿.md --limit 90
```

沉稳高管 4.2 字/秒(稳态),按这个排稿;权威时长只能 ffprobe 实测。

**MiniMax TTS 上游限流很硬**,脚本按 skill 的规矩固定 30 秒心跳重试
(不换请求、不指数退避),17 句大概要 40–60 分钟,急不得。

## 一件要提醒的事

卡片里的阅读器截图显示的是 **《Christmas in Camelot》(Magic Tree House #29)**
的一小段正文 —— 是版权书。拿来做 App 宣传截图问题不大(一小段、说明用途),
但如果你想更稳妥,可以把 `data/books/` 里换成 **Standard Ebooks** 或
**Project Gutenberg** 的公版书(项目本身就主打「找无 DRM 的版本」),
重跑截图即可。
