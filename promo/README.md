# 推广素材(2026-10-22 / 10-24)

给 X / 小红书 / 朋友圈用的图文与短视频。

**素材里的截图都是这个项目的真实运行界面**(本机局域网实例),
用的是项目自己的字体和纸面色 —— 推出去的东西和打开的东西是同一套。
家长页那组数字是为截图灌的**演示数据**(隔离实例,不含任何真实孩子记录)。

## 目录

```
promo/
├── cards/            图文卡片(小红书 3:4 + X 16:9 各一套)
│   ├── 01-cover.png        1080×1440  封面
│   ├── 01-cover-x.png      1600×900   封面(X)
│   ├── 02-reader.png       阅读器
│   ├── 03-shadow.png       跟读评分
│   ├── 04-kg.png           知识图谱
│   ├── 05-parent.png       家长页
│   └── 06-end.png          结尾
├── video/
│   ├── shadow-ebook-promo-9x16.mp4    1080×1920 · 40 秒 · 30fps(小红书/抖音)
│   ├── shadow-ebook-promo-16x9.mp4    1600×900  · 40 秒 · 30fps(X)
│   ├── cover-9x16.png                 视频封面(竖版)
│   └── cover-16x9.png                 视频封面(横版)
├── POSTS.md           发布文案:小红书 / X / 朋友圈 三套 + 发布节奏建议
├── COPY.md            图文版的文案(更详细,适合长文)
└── scripts/           生成脚本(想改文案或换素材时重新生成)
```

## 视频:中文旁白 + 烧进画面的字幕

40 秒,六个场景,**TTS 旁白**(edge-tts,zh-CN-XiaoxiaoNeural)+ 字幕跟着念到哪句亮哪句。
没有背景音乐(留白方便自己配,也免版权问题)。

| 时间 | 场景 | 旁白大意 |
|---|---|---|
| 0–6s | 封面 | 这是我自己做的英语阅读器,叫影子电子书 |
| 6–12s | 阅读器 | 纸的排版、点词查释义、一句一句地走 |
| 12–20s | 跟读评分 | 不说「词错了」,说「这个 o 的音还不稳」 |
| 20–27s | 知识图谱 | 教材、考纲、掌握度画在一张图上 |
| 27–34s | 家长页 | 诊断不是报表 |
| 34–40s | 结尾 | 不用云端,代码开源了 |

**场景时长由旁白音频的实际长度决定**,不是写死的 —— 改了旁白,画面自己跟上。

跟读那一帧是真的跑出来的:浏览器里注入 MediaStream 当麦克风,
录下「were working」,原句是「were walking」,界面真的显示
「『walking』里的 /AO/ 还不稳(长 o 像 go)」。

## 怎么重新生成

```bash
cd ~/shadow-learning
./start_lan.sh                                  # 素材来自真实界面
python3 promo/scripts/capture.py                # 1) 拍真实界面 → promo/shots/
python3 promo/scripts/cards.py                  # 2) 出卡片(竖版)
python3 promo/scripts/cards.py --landscape      #    出卡片(横版)
python3 promo/scripts/video_vo.py 9x16          # 3) 视频:合成旁白 → 渲帧 → 合成
python3 promo/scripts/video_vo.py 16x9
```

依赖:无头 Chrome(截图/渲染)+ ffmpeg(合成)+ edge-tts(旁白,项目自带)。
Python 只用标准库 —— 截图走自带的 CDP 驱动(`scripts/cdp.py`)。

改了旁白文案:改 `promo/scripts/video_vo.py` 里的 `SEGMENTS`,重跑即可。
改了图文文案:改 `promo/scripts/cards.py` 里的 `CARDS`,重跑即可。

## 一件要提醒的事

卡片里的阅读器截图显示的是 **《Christmas in Camelot》(Magic Tree House #29)**
的一小段正文 —— 是版权书。拿来做 App 宣传截图问题不大(一小段、说明用途),
但如果你想更稳妥,可以把 `data/books/` 里换成 **Standard Ebooks** 或
**Project Gutenberg** 的公版书(项目本身就主打「找无 DRM 的版本」),
重跑截图即可。
