# 🎨 Shadow Ebook — 美学规划(R16 设计系统)

> 本文档是前端美学重构的"宪法"。R16 实施时所有改动必须能映射回这份规范。
> 改动规范本身也走 PR review。

---

## 一、设计原则(3 条,不可妥协)

1. **内容优先** — 阅读体验 > 装饰。装饰元素必须有功能,纯好看不要。
2. **温暖安静** — 赤陶棕主调,服务学习,不让 UI 抢注意力。
3. **连贯可读** — 跨页面(ebook / tutor / grammar / parent / stats)语言一致,孩子切换页面不重学 UI。

---

## 二、色板(Semantic Tokens)

### 2.1 品牌色

| Token | Hex | 用途 |
|---|---|---|
| `--color-primary` | `#B86A4E` | 主按钮、链接、强调文字、关键图标 |
| `--color-primary-light` | `#D89B7E` | 主色 hover、淡背景、装饰 |
| `--color-secondary` | `#6B8A52` | 次按钮、成功提示、学习进度、成长类元素 |
| `--color-accent` | `#D4A574` | 提醒、点缀、奖状/勋章 |

### 2.2 背景层级(从远到近)

| Token | Hex | 用途 |
|---|---|---|
| `--bg` | `#FAF9F6` | 页面背景(米白,温暖) |
| `--bg-card` | `#FFFFFF` | 卡片/弹窗背景 |
| `--bg-dark` | `#F5F2EC` | 次级区(代码块、表格斑马纹、对比区块) |
| `--bg-overlay` | `rgba(45, 42, 38, 0.5)` | 模态遮罩 |

### 2.3 文字层级

| Token | Hex | 用途 |
|---|---|---|
| `--text-primary` | `#2D2A26` | 标题、正文主文 |
| `--text-secondary` | `#5A544C` | 副文、说明文字、标签 |
| `--text-disabled` | `#A39E94` | 禁用状态文字 |
| `--text-on-primary` | `#FFFFFF` | 主色背景上的文字 |

### 2.4 边框与分割

| Token | Hex | 用途 |
|---|---|---|
| `--border` | `#D6CFC0` | 普通边框、卡片描边 |
| `--border-strong` | `#A39E94` | 输入框聚焦、强调边框 |
| `--divider` | `#EBE5D8` | 分隔线 |

### 2.5 语义色

| Token | Hex | 用途 |
|---|---|---|
| `--danger` | `#C25B56` | 删除、错误、危险操作 |
| `--warning` | `#D4A574`(同 accent) | 警告、可恢复错误 |
| `--success` | `#6B8A52`(同 secondary) | 成功、完成、正确答案 |
| `--info` | `#7A8B9F` | 信息提示(蓝色低饱和,不抢眼) |

> **色板变更原则**:不引入新色,除非业务必须(如报名徽章之类)。如需引入,先在 PR 讨论。

---

## 三、字体系统

### 3.1 字体栈

```css
--font-sans:  -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Helvetica Neue',
              'Segoe UI', Roboto, sans-serif;
--font-mono:  'SF Mono', Menlo, Consolas, monospace;       /* 单词释义、音标 */
--font-num:   var(--font-sans);                            /* 数字等宽 = tabular-nums */

/* 三档分工(2026-10-19 补)。「像书不像 App」的关键不是换颜色,
   是把「读的东西」和「用的东西」分成两套字体。 */
--font-reading: Georgia, 'Iowan Old Style', 'Palatino',    /* 正文英文句子 */
               'Times New Roman', 'PingFang SC', sans-serif;
--font-display: 'Iowan Old Style', 'Palatino', Georgia,    /* 页头 / 大标题 */
               'Times New Roman', 'PingFang SC', sans-serif;
--font-ui:      var(--font-sans);                          /* 按钮、导航、标签 */
```

**为什么正文用系统衬线,而不是项目里已有的 Noto Serif SC**:那三个 ttf
每个 14MB、共 44MB,而本简报明写「不上 webfont」(局域网/平板加载慢)。
iPad 与 macOS 自带 Georgia / Iowan Old Style / Palatino,零下载、立刻可用。

**CJK 故意排在最后走 PingFang(黑体)**:手机上宋体细笔画会发虚,
10 岁孩子在小屏上读中文更难。衬线管英文、黑体管中文,是出版物的标准混排。

**正文行长 ≤ 34em(约 60~75 字符/行)**。超过 80 字符眼睛从行尾扫回行首
容易串行。必须用 `em` 而不是 `px`:孩子把字放大到 40px 时,行长要跟着缩,
不能变成一行 40 个大字。`.mode-book .reading-column` 就是这么写的。

### 3.2 字号 + 行高(8 段)

| Token | size / line-height | 用途 |
|---|---|---|
| `--text-xs`   | 12 / 16 | 极小字、版权、辅助说明 |
| `--text-sm`   | 14 / 20 | 标签、副文、表单辅助 |
| `--text-base` | 16 / 24 | **正文默认**(阅读场景最舒服) |
| `--text-lg`   | 18 / 28 | 重要正文、引文 |
| `--text-xl`   | 22 / 30 | h3、小节标题 |
| `--text-2xl`  | 28 / 36 | h2、卡片大标题 |
| `--text-3xl`  | 36 / 44 | h1、页面主标题 |
| `--text-display` | 48 / 56 | 大数字、统计页主角 |

### 3.3 字重

| Token | weight | 用途 |
|---|---|---|
| `--font-regular` | 400 | 正文 |
| `--font-medium`  | 500 | 强调、按钮文字 |
| `--font-semibold`| 600 | h1-h3、关键数据 |
| `--font-bold`    | 700 | 极少量:大数字、奖状名 |

### 3.4 排版微规则(R13 polish 升级)

| 规则 | 应用 | 原因 |
|---|---|---|
| `text-wrap: balance` | 所有 h1-h4 | 标题均衡断行 |
| `text-wrap: pretty` | 所有 p / li / figcaption | 段落避免孤儿词 |
| `font-variant-numeric: tabular-nums` | 数字、统计、进度 | 防止 9→10 切换抖动 |
| `-webkit-font-smoothing: antialiased` | 全局 | macOS 字重更黑更清晰 |
| `letter-spacing: -0.01em` | h1 / h2 | 大标题视觉收紧 |
| `letter-spacing: 0.02em` | 字母标签、全大写 | 可读性 |

---

## 四、间距(8 进制 + 4 微调)

```css
--space-0:  0;
--space-1:  4px;   /* 极紧:icon 内边距 */
--space-2:  8px;
--space-3:  12px;  /* 表单元素间距 */
--space-4:  16px;  /* 段落内元素 */
--space-5:  24px;  /* 卡片内边距 */
--space-6:  32px;  /* 区块间距 */
--space-7:  48px;  /* 章节间距 */
--space-8:  64px;  /* 页面顶部留白 */
--space-9:  96px;  /* 极少用:大标题区 */
```

> **微调 4px**:让 icon 跟文字的间距比 8px 更紧凑。其它按 8 走,杜绝 5/7/13 等野值。

---

## 五、圆角

```css
--radius-none: 0;
--radius-sm:   4px;   /* tag、小徽章 */
--radius-md:   8px;   /* 按钮、输入框 */
--radius-lg:   12px;  /* 卡片 */
--radius-xl:   16px;  /* 大卡片、模态框 */
--radius-2xl:  24px;  /* 极少用 */
--radius-pill: 9999px;/* 头像、胶囊按钮 */
```

**默认组件圆角**:
- 按钮 / 输入框: 8px
- 卡片: 12px
- 模态框: 16px
- 头像: pill

---

## 六、阴影(克制用)

```css
--shadow-sm:  0 1px 2px rgba(45, 42, 38, 0.06);
--shadow-md:  0 2px 8px rgba(45, 42, 38, 0.08);
--shadow-lg:  0 4px 16px rgba(45, 42, 38, 0.10);
--shadow-xl:  0 8px 32px rgba(45, 42, 38, 0.12);
```

**应用规则**:
- 卡片 hover: 从 `shadow-sm` → `shadow-md`,200ms ease-out
- 模态框: `shadow-xl`
- 弹起按钮(主操作): `shadow-md`

---

## 七、动效原则

### 7.1 时长

| Token | 时长 | 用途 |
|---|---|---|
| `--duration-fast`   | 100ms | 颜色/数字变化(避免慢) |
| `--duration-base`   | 200ms | **默认**(hover、active) |
| `--duration-slow`   | 300ms | 进入、模态框、列表 stagger |
| `--duration-slower` | 500ms | 路由切换、页面切换 |

### 7.2 缓动

```css
--ease-out:     cubic-bezier(0.16, 1, 0.3, 1);    /* 默认,自然减速 */
--ease-in:      cubic-bezier(0.4, 0, 1, 1);       /* 离场 */
--ease-in-out:  cubic-bezier(0.4, 0, 0.2, 1);     /* 双向 */
--ease-spring:  cubic-bezier(0.34, 1.56, 0.64, 1);/* 弹性:奖状弹跳、奖励出现 */
```

### 7.3 规则

- **不动画**:`width` / `height`(布局抖动)— 用 `transform`
- **stagger**:列表项 50ms 间隔,最多 8 项后跳过
- **prefers-reduced-motion**:全局尊重,关闭非必要动画

---

## 八、图标规范(2026-10-19 补)

**不用 emoji。** emoji 走系统彩色字体,渲染出来是高饱和的 3D 贴图,和
「纸 + 墨 + 赤陶」的低饱和基调直接打架,整页一眼就是「拼起来的」。
它也**无法跟随主题变色**,暗色模式下尤其扎眼。

图标统一放在 `web/styles/icons.css`,24×24 线性描边、1.8px、圆头圆角,
用 `mask` + `currentColor` 着色 —— 换主题自动跟随,零请求、零 webfont。

```html
<span class="ico ico-book" aria-hidden="true"></span>继续读
```

| 规则 | 说明 |
|---|---|
| 尺寸 | 默认 `1em`,跟着字号走;`ico--sm/lg/xl` 三档微调 |
| 单独出现 | 圆角方块 / 圆形按钮里的图标要加 `margin-right: 0`(见 icons.css 的 solo 列表) |
| 装饰性 | 一律 `aria-hidden="true"`,文字本身已经说明了一切 |
| 数量 | 语法卡这类「标题 + 副标题 + 徽章」已经够满的卡片**不要挂图标** |

**替代 emoji 时要连带改 JS**:`<span class="ico">` 是元素,
`textContent = '🔊'` 会把它整个抹掉。要换图标就切 class,
要换整段内容才用 `innerHTML`。

---

## 九、组件规范

### 8.1 按钮(4 类 × 3 尺寸)

| 类型 | 用途 | 样式 |
|---|---|---|
| Primary | 主操作(保存、提交、开始跟读) | `bg-primary`,文字白,hover 加深 5% |
| Secondary | 次操作(取消、返回) | 边框 `border-strong`,文字 primary |
| Ghost | 轻操作(链接式) | 文字 primary,hover bg-light |
| Danger | 危险(删除、改 PIN) | `bg-danger` |

| 尺寸 | 高度 | 内边距 | 字号 | 用途 |
|---|---|---|---|---|
| sm | **48px** | 16/28 | 18 | 默认交互下限(导航、返回、次要操作) |
| md | **60px** | 18/24 | 20 | 孩子的主动作:答题选项、确认、提交 |
| lg | **72px** | — | 32 | 播放 / 录音,圆形 |

**48px 是硬下限,没有例外。** 早期版本曾定义 32/40/48 三档,实际使用中
`web/kid-touch.css` 已用 `!important` 把所有交互元素强制到 48px/18px —— 因为
10 岁孩子在 iPad 上点不准小按钮。规范向实现看齐:R16 评审确认 sm 档上调至 48,
md / lg 按实际使用值补齐。

> ⚠️ 旧版 `kid-touch.css` 里的 `@media (orientation: landscape) and (max-height: 800px)`
> 会把 `--touch-min` 降回 44px,**违反本下限**,待清理。见 §14.2。

**active 状态**:scale(0.97),100ms ease-out
**disabled**:opacity 0.5,cursor not-allowed
**loading**:替换文字为 spinner(保留宽度,防抖动)

### 8.2 卡片

```css
background: var(--bg-card);
border: 1px solid var(--border);
border-radius: var(--radius-lg);
padding: var(--space-5);
box-shadow: var(--shadow-sm);
transition: box-shadow 200ms var(--ease-out);
```

可点击卡片:hover `shadow-md`,cursor pointer
统计卡片:无 hover,数字 `tabular-nums` + `--text-3xl` + `--font-semibold`

### 8.3 输入框

- 高度 **48px**,内边距 12/16,字号 18(与按钮 sm 档对齐)
- 边框 1px `border`,focus 变 `border-strong` + 淡主色 ring 3px
- error 状态:边框 `danger`,辅助文字也 `danger`
- PIN 输入框额外加大:4 位数字分开显示,每格 ≥ 56px,间距 12px
  (家长页孩子也会碰,尤其在平板上)

> ⚠️ `kid-touch.css` 的选择器列表里**没有 `input`**,所以家长页的 PIN 框
> 目前仍是旧的 40px,低于 48 下限。待补,见 §14.5。

### 8.4 进度条

- 高度 8px,圆角 pill
- 背景 `--bg-dark`,填充 `secondary`(成功) / `primary`(默认)
- 变化动效 600ms `--ease-out`

### 8.5 Tag / Badge

| 类型 | 用途 | 样式 |
|---|---|---|
| learning | 进行中 | bg `secondary` 10% + text `secondary` |
| review | 待复习 | bg `accent` 10% + text `accent` |
| mastered | 已掌握 | bg `primary` 10% + text `primary` |

字号 12,padding 4/8,圆角 `radius-sm`

---

## 十、信息层级

每页只能有**一个焦点**(视觉引导):

- index.html(原 ebook.html)→ 当前章节标题
- tutor.html → 当前句子 + 录音按钮
- parent.html → 今日学习时长 + 单词数(主指标)
- stats.html → 连续打卡天数

次要信息:字号小一级 + 文字 secondary
辅助说明:字号 xs + 文字 secondary

---

## 十一、状态反馈(默认 / hover / active / focus / disabled / loading)

| 状态 | 反馈 |
|---|---|
| 默认 | 设计稿状态 |
| hover | 颜色加深 / 阴影增强(200ms) |
| active | scale(0.97) + 颜色再加深(100ms) |
| focus | 主色 ring 3px(`outline-offset: 2px`,不是 `border`) |
| disabled | opacity 0.5 + cursor not-allowed + 移除 hover/active |
| loading | spinner + 禁用点击 + aria-busy |

**禁止**:`outline: none`(无障碍失败),只允许 `outline: none` + 自定义 ring。

---

## 十二、暗色模式(R17 已实现,本节补齐规范)

> 本节在 R17 实现之后补写。此前 DESIGN.md 写着"预留,本期不实现",
> 但 R17 已把暗色做完并合入 —— 规范滞后于实现,此处对齐。
> token 实际值见 `web/styles/tokens.css`,本节定义**规则**。

### 11.1 切换机制

| 方式 | 行为 |
|---|---|
| 不设 `data-theme` | 跟随系统 `prefers-color-scheme` |
| `data-theme="dark"` | 强制暗色 |
| `data-theme="light"` | 强制浅色(即使系统是暗色) |

孩子端的切换入口在 `web/theme.js`,家长端另给一个显式开关。

### 11.2 色板双轨原则

**token 变量名不变,只有值变。** 任何组件都不许写死颜色。

暗色不是把浅色"反相",而是**重新配一套**:同一个赤陶棕在深底上要变亮,
否则 `#B86A4E` 贴在 `#1A1714` 上对比度不够。

| Token | 浅色 | 暗色 | 变化逻辑 |
|---|---|---|---|
| `--bg` | `#FAF9F6` | `#1A1714` | 米白 → 暖黑(带一点棕,不是纯黑) |
| `--bg-card` | `#FFFFFF` | `#252220` | |
| `--color-primary` | `#B86A4E` | `#D89B7E` | **亮一档**,保识别度 |
| `--color-secondary` | `#6B8A52` | `#8FAA7A` | 同样亮一档 |
| `--text-primary` | `#2D2A26` | `#EDE6DA` | 暖黑 → 米白,避免纯白刺眼 |

### 11.3 暗色专属规则(代码里看不出来,必须写下来)

1. **不用纯黑背景。** `--bg` 最深到 `#1A1714`,保留暖调。纯黑(#000)在 OLED
   上边缘发白,且和暖色板打架。
2. **文字不用纯白。** 用 `#EDE6DA`。孩子长时间阅读,纯白刺眼。
3. **阴影换算。** 暗色下阴影几乎不可见,靠**边框**(`--border`)而非投影
   区分卡片。阴影保留但加深(`rgba(0,0,0,0.3~0.6)`),用于模态框悬浮感。
4. **封面图不反色。** 书籍封面、用户图片保持原样 —— 反色会让人物失真,
   比背景略亮一点即可(靠 `--bg-card` 抬一档)。
5. **波形图重算基线。** 跟读页的录音波形在暗色下描边要换用
   `--border-strong`,否则浅灰波形在深底上糊成一团。
6. **tint 类半透明底色统一降到 0.16~0.20**,比浅色下的浓度略高,
   因为深底上同样的透明度视觉浓度更低。

### 11.4 对比度底线

| 元素 | 要求 |
|---|---|
| 正文 / 背景 | ≥ 4.5:1 |
| 大字(≥18px 或 ≥14px bold)/ 背景 | ≥ 3:1 |
| 按钮文字 / 按钮底色 | ≥ 4.5:1 |

新增暗色 token 时,提交前用对比度工具验证,过不了就不许合。

### 11.5 迁移路径(已实施)

R17 完成:token 双轨 + `data-theme` 切换 + `theme.js` + e2e 覆盖
(`tests/e2e/test_dark_mode.py`)。

---

## 十三、迁移路径(R16 实施顺序)

1. **建立 token 文件** — `web/styles/tokens.css`(所有 CSS 变量)
2. **建立 base.css** — 重置 + 全局 + R13 polish 增强
3. **建立 components.css** — 按钮 / 卡片 / 输入框 / 进度条等
4. **改造 5 个 HTML** — 删除 inline `<style>`,改 link + 顶部 include partial
5. **CSP 收紧** — 删除 `script-src 'unsafe-inline' style-src 'unsafe-inline'`(此时已无 inline)
6. **CI 加视觉回归**(可选 R17+)

每步独立 commit,保证任意一步失败可回滚。

---

## 十四、本文档的演进

- 任何 token / 规范变更,先在本文件改 → PR review → 再写代码
- 不允许代码先于规范改动
- 评审时,把本文档给前端同事看,作为"设计语言统一性"的依据

---

## 十五、阅读器版式(2026-10-20 重做)

### 15.1 核心决定:整屏一张纸

原来的阅读器是三块不同底色的方框 —— 顶栏 `--bg-card`、正文 `--bg`、底栏 `--bg-card`。
这正是"网页布局"的观感来源:孩子看到的是"一个页面",不是"一页书"。

现在:

| 层 | 做法 |
|---|---|
| 纸 | `.reader-page` 铺满整屏,底色 `--bg-card` + `--paper-grain` |
| 顶栏 / 底栏 | 半透明玻璃 `--bg-glass` + `backdrop-filter: blur(16px)`,压在纸上 |
| 分界 | 一根 `--bg-glass-line` 发丝线,不是 `--border` |

层次来自**玻璃条的半透明**,不是来自"把页面切成几块"。
不支持 `backdrop-filter` 的浏览器退化成半透明纯色,不影响可读性。

### 15.2 顶栏

- 左:`← 书架` 图标 + 文字,48px 触控,hover 泛暖色
- 中:书名(`--font-display` 15.5px)+ 章节(11.5px,字距 0.06em)
- 右:`N / M` 胶囊,`--tint-primary` 底 + tabular-nums

### 15.3 正文行长

| 模式 | 行宽 | 说明 |
|---|---|---|
| `mode-book` | `34em` | 跟着字号走,20px 时约 66 字符 |
| `mode-focus` | `24em` | 大字号,一行 40~50 字符 |

用 em 不用 px:孩子把字从 20px 调到 30px,行长不变。

### 15.4 当前句标记

- focus 模式:左侧 2px 色条 + `--tint-active` 底色
- book 模式:**只留底色,去掉色条** —— 一句话可能就是一整段,
  内联盒跨行时色条只会在第一行露一截,底色又会把整段刷成荧光板
- 正在朗读:另加 `--tint-accent` 底色 + 3px 实色条(临时的,可以重)

`--tint-active` 单独开一个 token,比 `--tint-primary` 再淡一档,
暗色下要压得更淡(底色比浅色显眼得多)。

### 15.5 底栏

三列网格 `1fr auto 1fr`,朗读键在几何上真正居中。

- 左:上一页/下一页(幽灵键)+ 字号档(两个按钮拼成一段,中间一根发丝线)
- 中:「读一句」实心键 —— 底栏里唯一的实心,也是全站唯一的主操作
- 右:抽屉入口(圆形)

实心键的质感靠 `--fill-inset`(顶部一道内高光)+ `--fill-shadow`(接触影 + 弥散影),
不是靠渐变。按下时 `translateY(1px)` + 阴影收紧,**不缩放** ——
缩一下 10 岁孩子会以为点歪了。

### 15.6 列表页:不再白盒套白盒

「跟读学习」的选择列表原来是 3 个白圆角盒套在 1 个大白圆角盒里。
现在外层卡片保留(16px 圆角 + 发丝描边 + `--shadow-sm`),
内层条目改成**目录页样式**:条目之间一根 `--rule` 发丝线,悬停整行泛 `--tint-primary`。

同理:家长页 `.card`、统计页 `.stat-card`、语法页 `.grammar-card` 统一到
`1px solid var(--rule)` + `var(--shadow-sm)`;
语法卡 hover 时的「赤陶→草绿」渐变顶条删掉(低饱和基调里它是异色)。

### 15.7 目录

- 滤掉封面页 / 版权页 / 扉页 —— 它们不是章节,列在最前面只会让孩子对着 "Copyright" 发呆
- toc 的第 i 项**不一定**等于 chapters 的第 i 项(toc 常多出前置页),
  所以按标题对齐,对不上再退回按位置
- 目录项记 `data-chapter`,高亮时按它认领当前章(不能按 DOM 下标)
- 打开一本没读过的书:直接进正文第一页,不落在版权页上

---

## 十六、编辑式版式(2026-10-20 三轮)

前两轮把 emoji 换成了线性图标、把卡片阴影收紧了,截图对比下来还是一眼
「网页应用」而不是「一本书」。查过 editorial / paper 系的设计规范
(报头、扉页、索引页、发丝线分层)之后,差别集中在**骨架**上,不在细节里。

### 16.1 报头(masthead)

报纸的报头不是「浮在内容上方的一块导航」,它是**纸上的一部分**:

| 原来 | 现在 |
|---|---|
| 实心底 + `box-shadow` 投影 | 半透明玻璃 `--bg-glass` + 背景模糊,底下只留一根发丝线 |
| 品牌是粗体主色 | 品牌名用 `--font-display` 衬线、字距 0.05em、颜色是墨 |
| 栏目是圆角药丸,选中时一整块淡染 | 栏目当前项用一条 2px 主色线压在导航底边那根发丝线上 |
| 主题按钮是一块实心驼色 | 幽灵键:透明底 + 发丝线描边 |

**投影是「浮在上面」的证据**。报头本来就在纸上,不需要投影来证明自己浮着。

窄屏(≤900px)收起音色选择,≤720px 栏目收成纯图标、品牌只留方块印记;
所有栏目链接的触控高度统一 48px(首页原来只有文字高度 ~40px)。

### 16.2 扉页(page head)

原来:居中 + 一个 46px 圆角图标方块 + 居中标题 —— 那是 App 开屏页。
现在:一行小标签(eyebrow)+ 一个 38px 衬线标题 + 一条压着的发丝线,**左对齐**。

- eyebrow:`11px`、字距 `0.22em`、主色、带一个小图标
- 标题:`--font-display` 38px、字距 `-0.015em`、墨色
- 分隔:`1px solid var(--rule)`

页头底下那根线已经分过段,紧跟的第一块**不再画第二条** ——
两条平行的线隔 30px 摆着,看着像画错了。

### 16.3 压平:层级用发丝线,不用白盒子

「白盒套白盒」是模板感的主要来源。现在跟读 / 语法 / 统计三页的区块
直接坐在纸上,层级靠**一根上边线 + 上下留白**表达:

```css
.card {
    background: transparent;
    border: none;
    border-top: 1px solid var(--rule);
    border-radius: 0;
    padding: 26px 0 4px;
}
```

语法页的语法点改成**索引页条目**(三条栏、条目之间一条上边线),
hover 时那条线变主色、整行泛一点暖色。原来 hover 时闪的那条
「赤陶→草绿」渐变顶条删掉了。

统计页的连续学习天数大数字也**直接印在纸上**(上下各一条线),
不再装进白盒子里 —— 数字等宽 92px,用的是 `--font-display`。

### 16.4 「颜色是标点」

主色只留给**真正要点的按钮**:读一句、继续读、试听、保存。
换主题、换音色这些「换外观」的动作一律幽灵键。
标题是墨,不是主色 —— 小节标题原来整排是赤陶,比正文还吵。

### 16.5 继续读:书单上的一行

原来是一张白卡片套着书封 —— 等于把一本真书关进贺卡里,反而假。
现在撤掉盒子,只留书封自己的投影(它本来就是实物),
封面和文字之间竖一根发丝线,进度线铺满整列。

### 16.6 书眉(running head)

书里每一页顶上的「书名 · 章节」是同一个东西,层级要对:

- 书名:`10.5px`、字距 `0.16em`、大写、灰 —— 背景信息
- 章节:`--font-display` 15.5px、墨色 —— 孩子此刻在读的那一行

原来反过来了:衬线的书名比章节还显眼,重点错了。

### 16.7 其它

- 音色下拉框原本是浏览器默认件(白底 + 系统箭头),一眼露馅。
  改成 `appearance: none` + 透明底 + 发丝线描边 + 自己画的折角箭头
- 提示行加了 `margin-inline: auto` —— 之前它贴着舞台左边缘站,
  和居中的正文列错开一大截
- 家长页报头与其它页同一套(锁印记 + 衬线字),导航按钮改幽灵键

---

## 十七、已知偏差(DESIGN.md ↔ 代码)

R16 代码评审时记录。本节列的是**规范与实现不一致**的地方,以及裁决结果。
修完一条就删一条。

### 14.1 `kid-touch.css` 用 `!important` 覆盖整个设计系统 🔴

该文件对 `.btn`、`button`、`[class*="card"]` 等 10 个选择器统一施加
`!important`,强行改写 min-height / padding / font-size / border-radius。
后果:token 体系被旁路了 —— 改 `--btn-font` 不会生效,因为它被 `!important`
盖住了。

**裁决**:以实现为准(48/60/72 三档,见 §8.1),规范已上调对齐。
待办:把 `kid-touch.css` 的尺寸值改为读 token,去掉 `!important`,
让它退回"平板适配"而不是"第二套设计系统"。

### 14.2 iPad 横屏把按钮降回 44px 🔴

```css
@media (orientation: landscape) and (max-height: 800px) {
    :root { --touch-min: 44px; --btn-font: 16px; }
}
```

iPad 横屏正是**最常用**的姿势(README 写明"iPad 横屏为主"),
而这个 media query 恰好在横屏时把按钮降到 44px,**低于 §8.1 的 48px 下限**。

**裁决**:违反下限,待删。iPad 横屏空间紧张应通过减少留白、而不是缩小
点击目标来解决。

### 14.3 `kid-mode-toggle` 硬编码橙红渐变 🟡

```css
background: linear-gradient(135deg, #F59E0B, #EF4444);
```

违反 §2.5「不引入新色」。这是全项目唯一一处不走 token 的品牌色,
且橙红对"儿童友好"的调性是干扰项。

**裁决**:改为 `--color-accent` → `--color-primary` 的 token 渐变,
或直接用 `--color-accent` 纯色。

### 14.4 `kid-touch.css` 只在 2 个页面加载 🟡

`index.html` 和 `parent.html` 引了它,`tutor` / `grammar` / `stats` **没有**。
结果:跟读录音、语法答题这些孩子点得最多的地方,拿不到 48px 触控优化。

**裁决**:5 个页面应统一加载。待办。

### 14.5 `kid-touch.css` 漏掉 `input` 🟡

选择器列表是 `.btn, button, .clickable, [class*="btn"], [class*="option"],
[class*="card"], .nav-link, .book-card, .comp-option, .quality-btn,
.voice-select` —— **没有裸 `input`**。所以家长页的 PIN 输入框仍是 40px,
低于 §8.3 刚定的 48px 下限。

**裁决**:补 `input[type="text"], input[type="password"], input[type="number"]`
到选择器列表。待办。