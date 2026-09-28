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
```

**不上 webfont**(局域网/平板场景,加载 webfont 慢且偶尔失败)。

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

## 八、组件规范

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

## 九、信息层级

每页只能有**一个焦点**(视觉引导):

- index.html(原 ebook.html)→ 当前章节标题
- tutor.html → 当前句子 + 录音按钮
- parent.html → 今日学习时长 + 单词数(主指标)
- stats.html → 连续打卡天数

次要信息:字号小一级 + 文字 secondary
辅助说明:字号 xs + 文字 secondary

---

## 十、状态反馈(默认 / hover / active / focus / disabled / loading)

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

## 十一、暗色模式(R17 已实现,本节补齐规范)

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

## 十二、迁移路径(R16 实施顺序)

1. **建立 token 文件** — `web/styles/tokens.css`(所有 CSS 变量)
2. **建立 base.css** — 重置 + 全局 + R13 polish 增强
3. **建立 components.css** — 按钮 / 卡片 / 输入框 / 进度条等
4. **改造 5 个 HTML** — 删除 inline `<style>`,改 link + 顶部 include partial
5. **CSP 收紧** — 删除 `script-src 'unsafe-inline' style-src 'unsafe-inline'`(此时已无 inline)
6. **CI 加视觉回归**(可选 R17+)

每步独立 commit,保证任意一步失败可回滚。

---

## 十三、本文档的演进

- 任何 token / 规范变更,先在本文件改 → PR review → 再写代码
- 不允许代码先于规范改动
- 评审时,把本文档给前端同事看,作为"设计语言统一性"的依据

---

## 十四、已知偏差(DESIGN.md ↔ 代码)

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