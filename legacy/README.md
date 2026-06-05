# Legacy — Shadow Learning (原版多 Agent 跟读系统)

> ⚠️ **本目录已废弃**，仅保留用于历史回溯。
> 主线产品是 **Shadow Ebook**（基于 `../tutor_web.py` 的 Flask 电子书阅读器）。

## 背景

`shadow-learning/` 仓库最初是 **Shadow Learning** —— 一个用多 Agent 架构做"电影/动画对白跟读"的 Python 应用：
- `agents/` —— ASR / Recording / Scoring / Grammar / Vocabulary / Review / Audio 7 个 agent
- `services/shadow_learning_service.py` —— agent 编排服务
- `main.py` / `gui.py` / `webgui.py` / `web_server.py` —— 4 个不同入口（CLI / Tkinter / WebView / Flask）

后来项目转型为 **Shadow Ebook**（儿童英语电子书阅读器），新增了 `tutor_web.py` + `web/*.html` 完整一套。两套代码正交、几乎不共享，但一直共存于同一 repo。

经审计（2026-06）：
- `tutor_web.py` 完全没有 import 这里的任何模块
- `web/*.html` 完全没有调用这里定义的任何 API
- 唯一外部引用：`setup.sh` 的"运行 `python3 main.py`"提示（已修复，改为 `tutor_web.py`）

## 现状

| 文件 | 说明 |
|---|---|
| `main.py` | CLI 入口，需要 `agents/` + `services/` |
| `gui.py` | Tkinter GUI，Mac 上需 `brew install python-tk@3.14` |
| `webgui.py` | pywebview GUI |
| `web_server.py` | Flask 服务器（端口/路由与 tutor_web.py 不冲突，但功能正交）|
| `agents/` | 7 个 agent 模块 |
| `services/` | `ShadowLearningService` 编排类 |
| `test_basic.py` | `ScoringAgent` 单元测试（与 Shadow Ebook 无关）|
| `simple_web.html` | 上述 Flask 服务器的模板 |

## 是否可恢复

理论上可以运行 `python3 main.py` 启动 CLI 版；但 ASR 依赖系统级音频录制（sounddevice 等），实际可用性未验证。**不建议**作为产品形态继续投入。

如果未来想恢复该方向，建议：
1. 把这些代码从 `legacy/` 拆出去做成独立 repo
2. 不要尝试在 Shadow Ebook 里调用 `agents/`

## 移除建议

若确认不再需要历史回溯，可安全删除整个 `legacy/` 目录，不影响 Shadow Ebook 任何功能。
