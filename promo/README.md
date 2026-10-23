# 推广素材(2026-10-22)

给 X / 小红书 / 朋友圈用的图文与短视频。

**素材里的截图都是这个项目的真实运行界面**(本机局域网实例),
用的是项目自己的字体和纸面色 —— 推出去的东西和打开的东西是同一套。
家长页那组数字是为截图灌的**演示数据**(隔离实例,不含任何真实孩子记录)。

## 目录

```
promo/
├── cards/            图文卡片(两张一套)
│   ├── 01-cover.png        1080×1440  封面(小红书 3:4)
│   ├── 01-cover-x.png      1600×900   封面(X 16:9)
│   ├── 02-reader.png       阅读器
│   ├── 03-shadow.png       跟读评分
│   ├── 04-kg.png           知识图谱
│   ├── 05-parent.png       家长页
│   └── 06-end.png          结尾
├── video/
│   ├── shadow-ebook-promo-9x16.mp4    1080×1920 · 24 秒 · 30fps(小红书/抖音)
│   └── shadow-ebook-promo-16x9.mp4    1600×900  · 24 秒 · 30fps(X)
├── COPY.md           文案(小红书 / X / 朋友圈 三套 + 发布建议)
└── scripts/          生成脚本(想改文案或换素材时重新生成)
```

## 怎么重新生成

```bash
cd ~/shadow-learning
# 1) 起服务(素材来自真实界面)
./start_lan.sh
# 2) 拍真实界面 → 素材
python3 promo/scripts/capture.py
# 3) 生成卡片
python3 promo/scripts/cards.py            # 竖版
python3 promo/scripts/cards.py --landscape   # 横版
# 4) 生成视频(两个版本各约 2.5 分钟渲染)
python3 promo/scripts/video.py 9x16
python3 promo/scripts/video.py 16x9
```

依赖:无头 Chrome(截图/渲染)+ ffmpeg(合成视频)。
不需要装任何 Python 包 —— 截图用自带的 CDP 驱动,纯标准库。

## 改文案

文案在 `COPY.md` 里,是纯文本,改完直接复制去发。
卡片上的文字硬编码在 `scripts/cards.py` 的 `CARDS` 列表里,
视频的字幕在 `scripts/video.py` 的 `SCENES` 列表里 ——
改完重跑生成脚本即可。

## 一件要提醒的事

卡片里的阅读器截图显示的是 **《Christmas in Camelot》(Magic Tree House #29)**
的一小段正文 —— 是版权书。拿来做 App 宣传截图问题不大(一小段、说明用途),
但如果你想更稳妥,可以把 `data/books/` 里换成 **Standard Ebooks** 或
**Project Gutenberg** 的公版书(项目本身就主打「找无 DRM 的版本」),
重跑截图即可。

## 版本说明

- 图文:6 张一组(小红书发 3:4 竖版,X 发 16:9 横版)
- 视频:24 秒,6 个场景,无配音(留白方便自己配乐或加旁白)
- 视频里没有第三方音乐 —— 免版权问题
