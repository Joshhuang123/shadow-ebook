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

**正文(读英文句子)的 CJK 走 PingFang(黑体)**:手机上宋体细笔画会发虚,
10 岁孩子在小屏上读中文更难。衬线管英文、黑体管中文,是出版物的标准混排。

> ### ⚠️ 2026-10-20 修正:标题的中文必须走衬线
>
> 上面那条「CJK 走黑体」只对**正文**成立,**标题**不适用 ——
> 之前 `--font-display` 写的是
> `Iowan/Palatino/Georgia/Times → 'PingFang SC' → sans-serif`,
> 结果是:拉丁字形拿到衬线,**中文字形一路掉到 PingFang(黑体)**。
> 也就是说「英语跟读辅导」「语法学习」这些页面标题,
> 从头到尾都是黑体 —— 「像书不像 App」最关键的一环**根本没生效**。
>
> 修法:给 `--font-display` 补上**系统中文衬线**(不是 webfont):
> ```css
> --font-display: 'Iowan Old Style', 'Palatino', Georgia,
>                 'Songti SC', 'STSong', 'SimSun',
>                 'Source Han Serif SC', 'Noto Serif CJK SC', serif;
> ```
> `Songti SC`(宋体-简)是 macOS / iOS 自带,Windows 走 SimSun / 思源宋体,
> **全部零下载**。字体回退是**逐字**的:拉丁字形取 Iowan/Palatino,
> 中文字形自动落到后面的宋体 —— 正是出版物的标准混排做法。
>
> > ### ⚠️ 粗字重要用另一个栈:`--font-display-bold`
> >
> > 宋体只有 Light / Regular / Black 三档。直接写 `font-weight: 700`,
> > 浏览器会**合成加粗** —— 笔画糊成一片、字腔发黑,实测比 400 还难看。
> > macOS/iOS 的「Songti SC Black」是一个**独立字族**,里面就是真 Black,
> > 把它排在 `Songti SC` 前面就能拿到干净的粗体:
> > ```css
> > --font-display-bold: 'Iowan Old Style', 'Palatino', Georgia,
> >                      'Songti SC Black', 'STSongti-SC-Black',
> >                      'Songti SC', 'STSong', 'SimSun', serif;
> > ```
> > 拉丁字形不受影响:Iowan/Palatino 自带真粗体,排在最前面先被取走。
> > 凡是用 `--font-display` 且字重 ≥ 600 的地方,一律改用这个栈。
>
> 参照物:另一份做得好的稿子(deck)标题用 `Noto Serif SC 900`。
> 我们不上那个 webfont,但**要拿到同样的效果**就得让中文真的有衬线。
> 只靠改字号是拿不到这个效果的 —— 这是字体**字形**的问题,不是字号的问题。

**字重对比(2026-10-20 补)**:大标题 700,次级正文 **300**。
deck 那份稿子的质感有一半来自这个对比 —— 重字重的标题压着一段轻字重的
说明文字,层次立刻出来。≤13px 的小字不用 300(浅底上细笔画会发虚)。

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

**默认组件圆角**(2026-10-20 收紧):
- 按钮 / 输入框: 6px
- 卡片: 8px
- 模态框: 10px
- 头像: pill

**为什么收这么紧**:大圆角(16~24px)是 2015 年以后 App 模板的默认长相,
也是「一眼就像网页」的主要来源;印刷品、书、纸张都是近乎方角的。
参照物 deck 那份稿子全场 3px —— 质感有一半来自这个。
收到 3~14px 而不是 0:太生硬会吓到孩子,胶囊按钮和药丸选中态保留。

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

- 左:**上一句 / 下一句**(逐句)+ 字号档(两个按钮拼成一段,中间一根发丝线)
- 中:「读一句」实心键 —— 底栏里唯一的实心,也是全站唯一的主操作
- 右:抽屉入口(圆形)

实心键的质感靠 `--fill-inset`(顶部一道内高光)+ `--fill-shadow`(接触影 + 弥散影),
不是靠渐变。按下时 `translateY(1px)` + 阴影收紧,**不缩放** ——
缩一下 10 岁孩子会以为点歪了。

#### 为什么底栏是「上一句/下一句」,不是「上一页/下一页」(2026-10-21)

原话:「你直接按上一页下一页,这是干什么呢?核心是上一句跟下一句,
不然的话我怎么精确的控制让它读哪句话呢?」

一屏只放 3~10 句(按孩子的蓝思值算),**页是按句算出来的**。
所以页级导航对「让孩子读第 76 句」这件事毫无帮助 ——
一次跳 7 句,还是落不到要的那句上。逐句才是精确控制。

分工:

| 位置 | 动作 | 用途 |
|---|---|---|
| 底栏 | 上一句 / 下一句 | 精确控制读哪一句(主位) |
| 键盘 ← → | 上一句 / 下一句 | 同上 |
| 侧栏目录卡 | 上一页 / 下一页 + 「N / M 页」 | 快速略过一整屏(次要) |
| 键盘 PageUp/PageDown | 上一页 / 下一页 | 同上 |

- 逐句走到本页最后一句再按「下一句」,**页面自动翻过去** ——
  `updateDisplay()` 按 `currentSentenceIndex` 重新算这一屏的起始句,
  不用专门判断「是否越界」。
- 逐句按钮在第一句 / 最后一句时置灰,让家长知道到头了。
- 页级从底栏挪到侧栏的目录卡里:底栏主位只有一个语义,
  侧栏本来就是「导航列」,宽屏常驻,那一行一直看得见。
- 「上一句/下一句」的字样在窄屏也不隐藏(只到 ≤560px 才收成箭头)——
  箭头分不清是翻句还是翻屏。

#### 逐句移动别刷屏(2026-10-21)

逐句移动每一下都会触发一次翻译(往 mymemory 发请求 + 弹一个 5 秒的 toast)。
连点 5 下就是 5 个请求 + 一串提示盖在正文上,正好挡住要读的那句。

- **防抖 500ms**:停下来才真去翻,中间的请求直接丢掉(序号比对)。
- **宽屏不弹 toast**:侧栏常驻,译文直接写进侧栏那张卡,看得见。
- **窄屏才弹**:侧栏是收起的,弹一下让家长一眼看到译文;因为有防抖,
  连点也只弹一次。

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
- 目录卡顶部有一行页级翻页(「上一页 / N / M 页 / 下一页」)——
  底栏让位给逐句之后,页级挪到这里(见 §15.5)

### 15.8 侧栏:宽屏常驻,不再浮在正文上(2026-10-21)

R24 把侧栏从「常驻第三列」改成了抽屉(☰ 后面)。用起来两个问题:

1. **每读一章都要多点一次 ☰** —— 而「跟读评分」那块(朗读/跟读/录音)
   就在侧栏里。孩子要跟读,先得把侧栏拉开。
2. **拉开时正文被压成一片阴影** —— 遮罩是 `--bg-overlay`(0.5 黑),
   而这恰恰是孩子「一边看句子一边录音」的地方。

所以改回来,但不是简单回退:

| | 宽屏(≥1000px) | 窄屏(竖屏平板/手机) |
|---|---|---|
| 形态 | 右侧**常驻一列**,正文往左让 | 浮层,盖在正文上 |
| 遮罩 | 不要(没有浮层就没有阴影) | 保留,但调淡到 0.16 |
| ☰ 按钮 | 收起 / 展开侧栏 | 更多功能 |

几个细节:

- **常驻列不是浮层**,所以不画投影(`box-shadow: none`)——
  投影是「浮在内容上面」的信号,常驻的一列不该有。
- 正文让位靠 `padding-right`,顶栏/正文/底栏一起让,
  顶栏的书名才不会跑到侧栏底下去。
- 侧栏高度是固定的,所以顶部要**压紧**:封面 64→48px、
  出版信息(作者/出版社/系列/年份/语言/ISBN 六行)只留两行、
  目录列表 240→190px。压完「跟读评分」的录音键留在首屏里。
- **「章节测验」挪到跟读评分后面** —— 录音键是常按的,测验是偶尔做的。
- 遮罩换成单独的 `--bg-scrim` token(浅色 0.16 / 深色 0.32),
  不动 `--bg-overlay`(那个是弹窗用的,本来就该压暗)。
- 窄屏 ↔ 宽屏来回拖窗口时,浮层状态要收干净:
  窄屏开着浮层拖到宽屏,遮罩会留在那儿盖住正文。

分页测试用 Node 沙箱跑 `index.js`,那个沙箱里没有 `window.matchMedia`,
所以判断宽屏的那行做了存在性保护 —— 缺了就当窄屏。

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

#### 家长页也统一(2026-10-22)

家长页的 `.card` 其实早就是压平的(透明底 + 上边线),报头、底色、
扉页标题也都和全站一致。但还有三处**漏网的旧语言**:

1. **「阅读声音」的三块白盒子** ——
   `#ttsCard .setting-item` 比 `.setting-item` 更具体,
   把全站压平的那一层**加了回来**(`background: var(--bg-card)` +
   一整圈边框)。白盒子浮在纸上,一眼就不是一套。
   → 压平:透明底 + 一根发丝线。输入框自己还是白底 —— 那是控件,不是盒子。
2. **「书籍来源」的四个圆角框** —— 全站早就是「发丝线 + 方角」了
   (统计页那四个指标块就是 `radius: 0` 的发丝线框),圆角框是上一代的语言。
   → 改成方角发丝线框。
3. **登录页的居中大标题** —— 「家长模式」原来是无衬线 28px 居中 +
   一块淡染底的方锁图标,那是「App 开屏页」的说法。
   → 换成全站的扉页式(小标签 + 宋体黑 44px + 一根发丝线,左对齐),
   锁图标进小标签,PIN 框和「默认密码」都跟着左对齐。

   顺带删掉两条会**误伤**新扉页的死规则:`.login-section h2` /
   `.login-section p` —— 后者比 `.page-head-eyebrow` 更具体,
   留着会把小标签的颜色和下边距改掉。

教训:**压平不能只改基础类**。更具体的选择器(`#id .class`)会
把已经压平的那一层又加回来。改完要真去页面上扫一遍
(找出所有「背景不是透明」的块),别只看 CSS 读着顺不顺。

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

## 十七、质感来自哪里(2026-10-20 四轮 · 参照物)

这轮的参照物是另一份做得好的 deck(暖金黑主题)。把它的做法拆开,
能落到本项目的有五件事,按收益排序:

| # | 做法 | 本项目怎么落 | 收益 |
|---|---|---|---|
| 1 | 标题用**真中文衬线** | `--font-display` 补 `Songti SC`(系统自带,零下载) | **最大** —— 之前中文标题一直是黑体 |
| 2 | 大字重 700 + 次级正文 300 | 标题 700,副标题/说明 300(≤13px 除外) | 大 |
| 3 | 圆角收到近乎方角 | token 从 4/8/12/16/24 收到 3/6/8/10/14 | 大 |
| 4 | 纸面加极淡的暖光 | `--paper-glow`,铺满 `html body` | 中 |
| 5 | 编号/页码用等宽 + 大字距 | 目录序号、页码胶囊 | 小但提气质 |

**没有搬的**:deck 的暗底金黑配色(和本项目「纸 + 墨 + 赤陶」冲突,
简报也明写禁高饱和与金属色渐变);它的 1920×1080 固定画布(网页是自适应的);
它的英文拉丁引文字体 Cormorant Garamond(本项目正文是英文句子,
用 Iowan 就够)。

**一份好的稿子不等于一套配色,但它能告诉你「质感」到底由哪些变量决定** ——
这次查完才发现,最大的一项根本不是颜色,是**中文字形**:
之前所有标题都在黑体上,再怎么调字号、圆角、间距都还是「网页」。

---

## 十八、导入(2026-10-20)

这一页是**工具**,不是收藏品。它必须能一直加书,不然就是一��性的。

### 18.1 入口必须常驻

以前「导入新书」只出现在书架网格**最后一张卡**里,而且**只有家长登录后才渲染**。
结果:孩子和未登录的家长在整页上找不到任何能加书的地方。

现在入口在**书架标题行右边**,一直显示;下面一行小字说明支持哪些格式。
点它 → 没登录就在原地问密码(4 位)→ 输完接着选文件,不用跳去 /parent 再自己找回来。

### 18.2 支持的格式

`EPUB / PDF / TXT / Markdown / HTML / DOCX / MOBI / AZW3`。

**为什么是这几个** —— 查了 2022 年欧洲电子书市场的主流文本格式分布
(EPUB2+EPUB3+PDF 合计 85%~97%,MOBI/AZW3/FB2/DJVU 等"其它"占 1%~25%),
加上 2024 年数字出版协会的报告(主流格式超 12 种,EPUB/PDF/MOBI/AZW3/
DJVU/FB2 六种占 92% 份额),再加各平台的支持情况:

| 平台 | 主力格式 | 说明 |
|---|---|---|
| Apple Books / Google Play / Kobo | EPUB(70%+) | 开箱即用 |
| Kindle | MOBI / AZW3 | 正在往 EPUB 迁;2026 年 1 月起 Kindle 书的「无 DRM EPUB」可下载 |
| 图书馆(OverDrive / Libby) | EPUB + PDF(下载到电纸书) | 但借的书**带 DRM** |
| 俄罗斯/东欧 | FB2 | 少见,暂不支持 |
| 扫描件 | DJVU / 扫描版 PDF | 本质是图片,需要 OCR |

结论:**EPUB + PDF 就覆盖了 95% 的场景**("EPUB for books, PDF for documents"),
TXT/DOCX/HTML/MOBI 是补边。所以重点不是再堆格式,而是**把 DRM 说清楚**。

### 18.3 DRM —— 真正的拦路虎

家长最常见的「导不进来」原因不是格式,是**加密**:

- 图书馆借的书(OverDrive/Libby)→ Adobe ACSM,`META-INF/sinf.xml`
- Kindle 买的 → ADEPT,`META-INF/encryption.xml`
- Readium LCP → `META-INF/license.lcpl`

这些文件**结构完全合法、扩展名也是 .epub**,但正文是加密的。
不提前拦的话,家长看到的是几百页之后一句「没读到正文」。

现在导入时提前识别,并明确告诉他该去哪拿没加密的版本
(Standard Ebooks / Project Gutenberg / Internet Archive /
亚马逊的「下载无 DRM EPUB」)。

⚠️ 字体嵌入混淆(font obfuscation)也用 `encryption.xml`,但它**不是 DRM** ——
误判的话一大半正常 EPUB 会被冤枉。判据是 encryption.xml 里有没有
DRM 专用的 Algorithm URI。

除了 EPUB 走原有的解析器(那里面有二十来个历史 bug 的修复,不动),
其它格式都经过 `extensions/book_formats.py`,产出**和 EPUB 完全一样**的
`book_data` 结构 —— 下游(查词 / 朗读 / 跟读 / 蓝思值 / 封面)不需要为每种
格式各写一套。

### 18.4 导入链路上修掉的坑

| 坑 | 后果 |
|---|---|
| `secure_filename` 会把非 ASCII 全删 | 「小王子.txt」被削成「.txt」→ 判成不支持的格式 |
| 分句器只认 `.!?` 和「≥3 个空格分词」 | 一整段中文是 1 个「词」→ **中文书导入进来是空的** |
| 排版连字(U+FB01 等)没还原 | PDF 正文里一堆方框 |
| 中文书名 sanitize 后只剩残骸 | 「测试 EPUB 书」和「我的 EPUB 书」撞同一个 id,第二本永远导不进去 |
| 导入出 0 章 0 句也算成功 | 家长看到「导入成功」,孩子打开是一页空白 |
| 每章不足 3 句的章被整章丢掉 | 短章节的书整本变空 |
| `makeFallback` 返回 DOM 元素 | 塞进 innerHTML → 页面出现「[object HTMLDivElement]」 |

最后一条是这轮才暴露的老 bug —— 以前每本书都有封面,无封面那条路径从没被走到。

### 18.5 目录预览 + 章节选择

一本书 24 章,家长往往只想导其中几章(版权页、目录、试读、作者的
「本书献给…」都不要)。所以**只选一本时**先弹目录预览:勾选 → 导入。

实现上有个关键决定:**预览时把文件暂存在服务器上,导入时带 token 上来**。
否则 50MB 的 PDF 要在局域网上传两遍。暂存区一小时过期自动清。

章节选择语义:勾哪几章就导哪几章;**一个都没勾 = 全都要** ——
不能导出一本空书。

### 18.6 失败必须说人话

- 扫描版 PDF → 「这个 PDF 里几乎提取不到文字,多半是扫描版…需要先做 OCR」
- 重复导入 → 「已经有一本同名书了,改个文件名再试」
- 会话过期 → **自动弹密码框,输完接着导**(不用重新选文件)

批量导入用面板逐本列结果,不用一串 alert()。

### 18.7 家长页的 DRM 指引

「书导不进来」是家长最常问的问题,而答案不是格式、不是操作 ——
是 DRM。家长页里有一张卡直接回答它,并给出四个没加密的来源
(Standard Ebooks / Project Gutenberg / Internet Archive /
亚马逊的无 DRM EPUB)。

---

## 十九、已知偏差(DESIGN.md ↔ 代码)

R16 代码评审时记录。本节列的是**规范与实现不一致**的地方,以及裁决结果。
修完一条就删一条。

### 14.1 `kid-touch.css` 用 `!important` 覆盖整个设计系统 ✅ 已解决(2026-10-20)

该文件对 `.btn`、`button`、`[class*="card"]` 等 10 个选择器统一施加
`!important`,强行改写 min-height / padding / font-size / border-radius。
后果:token 体系被旁路了 —— 改 `--btn-font` 不会生效,因为它被 `!important`
盖住了。

**2026-10-20 已解决**:家长页是唯一还加载这个文件的地方
(`index.html` 早就是注释掉的)。它挂着的时候,家长页的导航是
`border-radius: 24px !important` 的大药丸、字号被强制拉到 20px ——
**家长页因此跟其它页长得完全不一样**,而根因一直没被找到。
现在把 `<link href="/kid-touch.css">` 从 `parent.html` 里摘掉,
48px 触控下限改由设计系统自己保证:
- `base.css`:裸输入框 `min-height: 48px`(之前靠 `!important` 撑着)
- `components.css`:导航链接 `min-height: 48px`
- 各页 CSS:目录项 48px、模式切换按钮 48px、字号档 48px
- `parent.css`:`.btn-preset` 36→48、`.bi-btn` 40→48、`.link-btn` 25→48

`kid-touch.css` 文件本身保留(历史遗留),但**任何页面都不再加载它**。

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