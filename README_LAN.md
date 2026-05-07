# 🦊 Shadow Learning - 原版阅读社团版

## 简介

专为小学生原版阅读社团设计的英语学习工具，支持：
- 电子书阅读 + 查词 + 生词本
- 英语跟读练习 + 波形对比
- 语法学习
- 艾宾浩斯复习
- 学习数据统计

## 快速启动

### 方式一：一键启动（Mac）

```bash
./start_lan.sh
```

### 方式二：手动启动

```bash
cd /Users/huangjunhai/shadow-learning
source venv/bin/activate
python3 tutor_web.py
```

启动后显示：
```
🦊 Shadow Learning - 原版阅读社团版
======================================
🌐 本机访问: http://localhost:5002
📱 局域网访问: http://192.168.x.x:5002
```

## 社团使用

1. **老师电脑**运行 `python3 tutor_web.py`，确保显示器接投影
2. **学生平板/电脑**连接同一 WiFi，打开浏览器访问显示的局域网地址
3. 每个学生用自己的平板，数据存在各自浏览器里（localStorage）
4. 可导入适合小学生程度的 EPUB 书

## 添加新书

1. 打开网页版 http://localhost:5002/ebook
2. 点击"导入 EPUB"按钮上传文件
3. 等待解析完成

## 推荐书单（已导入）

| 书名 | 蓝思值 | 难度 |
|------|--------|------|
| Magic Tree House #29 | 500L | 入门 |
| Percy Jackson: Lightning Thief | 590L | 入门 |
| Harry Potter #1 | 880L | 中级 |
| Diary of a Wimpy Kid | 800L | 中级 |

## 注意事项

- 建议使用 Chrome/Safari 浏览器
- 平板需要麦克风权限（跟读功能）
- 首次使用需要联网下载依赖，之后可离线使用基础功能
- 数据保存在浏览器本地，建议每学期导出备份
