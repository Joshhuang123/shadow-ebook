# 🧪 E2E 测试套件(Playwright)

> 覆盖 5 个核心页面 (`/` `/tutor` `/grammar` `/parent` `/stats`) 的浏览器层行为。
> 用 Playwright sync API 起一个真 Chromium,加载 Flask 子进程,跑 assert。

---

## 目录

- [设计目标](#设计目标)
- [架构](#架构)
- [文件结构](#文件结构)
- [本地运行](#本地运行)
- [CI 流水线](#ci-流水线)
- [用例清单](#用例清单)
- [已知 skip / TODO](#已知-skip--todo)
- [写新测试](#写新测试)
- [故障排查](#故障排查)

---

## 设计目标

- 测"**真实浏览器里跑出来的行为**",不只 mock HTTP —— 抓 CSP 报错、inline-style 阻断、客户端 JS 路由、localStorage 持久化 等纯 unit test 抓不到的回归
- 测**自己起的 Flask 子进程**(`subprocess.Popen([sys.executable, ...])`),不连外部 server
- 一次 Flask 启动 + 一次 Chromium 启动,**session 级共享**,避免每个 test 都重启服务
- 默认 headless + commit-not-load,跑 30+ case 不至于超时

---

## 架构

```
tests/e2e/conftest.py      session 级 fixture:
                           - app_url: 启动 Flask 子进程,绑 0 端口
                           - browser: 一个 Chromium 实例(session 共享)
                           - page:    每个 test 新 tab(默认加载 /)
tests/e2e/test_navigation.py   5 页跳转 / nav-link / theme 持久化
tests/e2e/test_dispatcher.py   data-action 路由(map 100+ 按钮 / dialog 关闭)
tests/e2e/test_dark_mode.py    4 页 theme button,light↔dark 亮度差 ≥ 0.3
```

**关键点**:
- `app_url` 通过 `find_free_port()` 让 OS 分配端口,CI / 本地都不撞
- `wait_until='commit'` 而不是默认 `'load'`:跑 30+ test 后 Chromium 累,`load` 事件触发慢,`commit` 等到首字节就返
- Chromium launch args: `--disable-dev-shm-usage --disable-gpu --no-sandbox`(为 Linux CI 容器调过)

---

## 文件结构

```
tests/e2e/
├── __init__.py                 # 让 pytest 把它当成 package(空文件即可)
├── conftest.py                 # session-scope Flask + browser + page fixture
├── test_navigation.py          # ✦ 5 页跳转 + 主题持久化
├── test_dispatcher.py          # ✦ data-action 路由分发(防 inline onclick 回归)
└── test_dark_mode.py           # ✦ 4 页 light/dark 切换,NTSC 亮度差断言
```

> 任何想加的 e2e 用例都进这个目录,**不要**跟 `tests/test_*.py`(单元)混。

---

## 本地运行

```bash
# 1. 装基础依赖(Flask + edge-tts)
pip install -r requirements.txt

# 2. 装 e2e 依赖(pytest + playwright Python 包)
pip install pytest playwright

# 3. 装 Chromium 浏览器二进制 + Linux 系统依赖(macOS 跳过这一步的 --with-deps)
playwright install chromium
# Linux:
playwright install --with-deps chromium

# 4. 跑
python -m pytest tests/e2e/ -v
```

**只跑一个文件 / 一个测试**:
```bash
python -m pytest tests/e2e/test_navigation.py -v
python -m pytest tests/e2e/test_dark_mode.py::test_body_brightness_flips_with_theme -v
```

**带 trace(失败时录屏)**:
```bash
playwright install  # 确保 chromium 装好
python -m pytest tests/e2e/ -v --tb=short -x
```

---

## CI 流水线

`.github/workflows/test.yml` 跑两个并行 job:

| Job | OS | 跑什么 | 说明 |
|-----|-----|--------|------|
| **unit** | macos-latest | `pytest -q --ignore=tests/e2e` | 现有 guard tests,保留 macOS 习惯 |
| **e2e** | ubuntu-latest | `pytest tests/e2e/ -v --tb=short` | 新加,Chromium 在 Linux 更快 |

**e2e job 步骤**:
1. checkout
2. setup-python 3.12 + pip cache
3. `pip install -r requirements.txt` + `pytest==9.0.3 playwright==1.60.0`
4. `playwright install --with-deps chromium`
5. `pytest tests/e2e/ -v --tb=short`
6. 失败时 `upload-artifact` `tests/e2e/`(retention 7 天)

> e2e job 故意用 **ubuntu-latest** 而不是 macos:
> - Linux 容器起得更快(macOS runner 通常 +30-60s)
> - Chromium 的 headless 渲染在 Linux 容器里更稳定
> - 省 macOS runner minutes(免费额度 2k/月,自费 runner $0.08/min)

---

## 用例清单

### test_navigation.py
- `test_all_five_pages_return_200` — `/` `/tutor` `/grammar` `/parent` `/stats` 全部 200 + body
- `test_nav_link_round_trip[source→target]`(参数化 4×4) — 每页 nav-link 真能跳到目标
- `test_nav_links_present[path]`(参数化 4 页) — top-nav href 集合 = `[/ /tutor /grammar /stats]`
- `test_theme_persists_across_navigation` — 切 dark 后跳 `/grammar`,theme 仍是 dark
- `test_parent_requires_login` — `/parent` 返回 200,且 body 含「家长/登录/PIN/密码」关键字

### test_dispatcher.py
SAFE_CLICKS = `{cycleTheme, setMode, changeFontSize, toggleSidebar, toggleTocSidebar,
closeARPanel, closeCompModal, closeReviewModal, closeWordModal, closeGrammar,
closePractice, clickStopPropagate}`
- `test_resolve_all_routes[path]`(参数化 4 页) — 每个 path 上的 data-action selector 都解得出 route
- `test_safe_click_dispatches[action]`(参数化 SAFE_CLICKS) — 点按钮 → 对应 route 被调用,异常没冒泡
- `test_arg_parsing_numeric` — `changeFontSize(+1)` 类参数能正确传给 route
- `test_dispatch_via_child_element` — 点击 `<button><svg data-action=...></svg></button>` 的 SVG 子元素也能 dispatch

> 目的:防有人把 onclick 写回 HTML(这类 inline handler 会让 CSP `script-src 'self'` 报违反)。

### test_dark_mode.py
- `test_body_brightness_flips_with_theme[/+path]`(参数化 4 页) — 切 dark 后,bg 渐变首色亮度差 ≥ 0.3
- `test_themeBtn_cycles_through_modes[path]`(参数化,但 `/stats` skip)
  - 第 1 击 day→night,`data-theme=dark`
  - 第 2 击 night→auto,`delete root.dataset.theme`(JSON 序列化成 None)
  - 第 3 击 auto→day,`data-theme=light`

---

## 已知 skip / TODO

- **`/stats` reload 第二次 DCL 超时**:reload 后 `stats.js` 的 render 逻辑在 `localStorage` 累积后跑 long task,DCL 30s 内不一定 fire。`test_themeBtn_cycles_through_modes` 对 `/stats` skip。
  - Fix 路径:优化 `stats.js` 的 `render()` 或拆分成 microtask + 测试侧用 `wait_for_function`
- **CSP inline-style 报错**:`app.py` 的 CSP 已经 `style-src 'self'`,但 HTML 里还有遗留 `style="..."` 属性。console 会喷 `Applying inline style violates...`。
  - conftest 已 filter 掉(`known_console_noisy: R16.x 应该清干净`)
  - 真要清:把所有 `style="..."` 改 CSS class
- **`MEMORY.md` 12% 截断警告**:不在 e2e 范畴,但 bootstrap 通道相关,跟 dashboard 显示 stale handoff 是同类问题

---

## 写新测试

**模板**(用 `page` + `app_url` fixture):
```python
from __future__ import annotations
import pytest


def test_something(page, app_url):
    page.goto(app_url + '/tutor', wait_until='commit')
    page.locator('#someBtn').wait_for(state='visible', timeout=30000)
    page.locator('#someBtn').click()
    page.wait_for_timeout(200)
    assert page.locator('.result').inner_text() == 'expected'
```

**几条规则**:
1. **必须 import `app_url`** —— 别 hardcode 端口
2. **goto 用 `wait_until='commit'`** —— 别用默认 `'load'`,30+ case 后会超时
3. **selector timeout 给 30s** —— 第一次渲染计算可能慢(`/stats` 的 streak + chart)
4. **用 `.first`** —— 多个匹配时不要让 pytest 直接挂
5. **console error filter** —— 在 conftest 已经处理 CSP;新错误请保留并加个过滤

---

## 故障排查

| 症状 | 原因 / 修复 |
|------|-------------|
| `playwright install` 卡住 | 换 npm: `npm i -g playwright && npx playwright install chromium` |
| Linux 缺 `libnss3` 等 | `playwright install --with-deps chromium` 自动 apt 装 |
| `port already in use` | conftest 用 `find_free_port()`,理论不会撞;若真是,重启 runner |
| 第一次 `test_*` 超时 | 检查 Flask 是否真的启动:看 stdout 子进程输出(`_wait_ready` 失败会 propagate) |
| `Page.goto: Timeout` | 八成是 `wait_until='load'` 撞了 Chromium 疲劳 → 改 `commit` |
| `app.py` import 失败 | conftest 第一行加了 `sys.path.insert(0, ROOT)`;若改名 `__init__.py` 可能丢 |
| CSP `style-src` 报错 | conftest 已 filter;若是新错误,请保留并加注释 |

---

## 参考

- [Playwright Python sync API](https://playwright.dev/python/docs/api/class-page)
- [conftest.py 完整源码](../tests/e2e/conftest.py)
- [CI 配置](../.github/workflows/test.yml)
