# Knowledge Manager

> 一款基于 Python + PySide6 的 Windows 桌面 PDF 知识管理工具，集阅读、批注、词汇收集、AI 解释与测验于一体。

## 功能特性

- **PDF 阅读**：基于 PyMuPDF 的高性能渲染，支持缩放、滚动、多页连续浏览
- **文本批注**：高亮标记、页面笔记，数据持久化到本地 SQLite
- **词汇收集**：划词收藏，支持批量生成 AI 释义
- **AI 解释**：对接任意 OpenAI 兼容 API（OpenAI / DeepSeek / Kimi 等），支持流式回复与图文多模态解释
- **测验模式**：从 Markdown 导入题库，支持分主题练习与答题统计
- **主题切换**：内置 Dark / Light / Nature 三套主题

## 界面预览

（截图占位，欢迎补充）

## 技术栈

| 层级 | 技术 |
|------|------|
| GUI 框架 | PySide6 >= 6.5.0 |
| PDF 引擎 | PyMuPDF (fitz) >= 1.23.0 |
| AI API | requests >= 2.31.0 |
| 数据库 | SQLite3 |
| 构建工具 | PyInstaller |
| 语言 | Python 3.x |

## 快速开始

### 环境要求

- Windows 10/11
- Python 3.12+（推荐）

### 安装依赖

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

### 运行（开发调试）

```bash
# 无控制台窗口
run.bat

# 或直接在终端运行
venv\Scripts\python main.py
```

### 构建独立可执行文件

```bash
build.bat
```

输出目录：`dist\KnowledgeManager\KnowledgeManager.exe`

## 项目结构

```
Knowledge-Manager/
├── main.py                  # 入口
├── requirements.txt         # 依赖
├── KnowledgeManager.spec    # PyInstaller 配置
├── build.bat                # Windows 构建脚本
├── run.bat                  # 启动脚本
├── icon.ico / icon.png      # 应用图标
├── design/                  # 设计文档
├── core/                    # 后端模块
│   ├── database.py          # SQLite 数据层
│   ├── api_client.py        # AI API 客户端
│   ├── pdf_engine.py        # PyMuPDF 封装
│   ├── quiz_parser.py       # Markdown 题库解析
│   ├── logger.py            # 日志
│   ├── theme_colors.py      # 主题配色
│   └── utils.py             # 工具函数
└── ui/                      # 前端 Qt 组件
    ├── main_window.py       # 主窗口
    ├── pdf_tab_widget.py    # PDF 标签页
    ├── pdf_scroll_view.py   # PDF 滚动视图
    ├── quiz_*.py            # 测验模式相关
    ├── vocab_panel.py       # 词汇面板
    ├── note_panel.py        # 笔记面板
    ├── ai_chat_panel.py     # AI 对话面板
    ├── theme_manager.py     # 主题管理
    └── ...
```

## 配置 AI 提供商

首次运行时，通过 **设置** → **AI 提供商** 添加你的 API Key：

- 支持任何 OpenAI 兼容端点
- 可配置代理、温度、最大 token、是否流式输出

## 数据说明

- 所有用户数据（高亮、笔记、词汇、AI 提供商配置）存储在项目根目录的 `data.db` 中
- 应用退出时会自动备份数据库到 `backup/` 目录
- 导出的词汇文件保存在 `vocab/` 目录

> ⚠️ 本项目为本地单用户工具，API Key 以明文形式存储在本地 SQLite 中，请勿共享数据库文件。

## 贡献

欢迎提交 Issue 或 PR！

## 许可证

[MIT](LICENSE)
