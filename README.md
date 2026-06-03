# Knowledge Manager

> A Windows desktop PDF knowledge management tool built with Python + PySide6, integrating reading, annotation, vocabulary collection, AI explanations, and quizzes.

[English](README.md) | [简体中文](README.zh-CN.md)

## Features

- **PDF Reading**: High-performance rendering powered by PyMuPDF, with zoom, scroll, and continuous multi-page browsing
- **Annotations**: Text highlighting and per-page notes, persisted to local SQLite
- **Vocabulary Collection**: Select and collect words, with batch AI definition generation
- **AI Explanations**: Connect to any OpenAI-compatible API (OpenAI / DeepSeek / Kimi, etc.), supporting streaming responses and multimodal image explanations
- **Quiz Mode**: Import question banks from Markdown, with topic-based practice and answer statistics
- **Theme Switching**: Built-in Dark / Light / Nature themes

## Tech Stack

| Layer | Technology |
|-------|------------|
| GUI Framework | PySide6 >= 6.5.0 |
| PDF Engine | PyMuPDF (fitz) >= 1.23.0 |
| AI API | requests >= 2.31.0 |
| Database | SQLite3 |
| Build Tool | PyInstaller |
| Language | Python 3.x |

## Quick Start

### Requirements

- Windows 10/11
- Python 3.12+ (recommended)

### Install Dependencies

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

### Run (Development)

```bash
# No console window
run.bat

# Or run directly in terminal
venv\Scripts\python main.py
```

### Build Standalone Executable

```bash
build.bat
```

Output: `dist\KnowledgeManager\KnowledgeManager.exe`

## Project Structure

```
Knowledge-Manager/
├── main.py                  # Entry point
├── requirements.txt         # Dependencies
├── KnowledgeManager.spec    # PyInstaller config
├── build.bat                # Windows build script
├── run.bat                  # Launch script
├── icon.ico / icon.png      # App icons
├── design/                  # Design documents
├── core/                    # Backend modules
│   ├── database.py          # SQLite data layer
│   ├── api_client.py        # AI API client
│   ├── pdf_engine.py        # PyMuPDF wrapper
│   ├── quiz_parser.py       # Markdown quiz parser
│   ├── logger.py            # Logging
│   ├── theme_colors.py      # Theme palettes
│   └── utils.py             # Utilities
└── ui/                      # Frontend Qt widgets
    ├── main_window.py       # Main window
    ├── pdf_tab_widget.py    # PDF tabs
    ├── pdf_scroll_view.py   # PDF scroll view
    ├── quiz_*.py            # Quiz mode widgets
    ├── vocab_panel.py       # Vocabulary panel
    ├── note_panel.py        # Notes panel
    ├── ai_chat_panel.py     # AI chat panel
    ├── theme_manager.py     # Theme management
    └── ...
```

## Configure AI Providers

On first run, add your API Key via **Settings** → **AI Providers**:

- Supports any OpenAI-compatible endpoint
- Configurable proxy, temperature, max tokens, and streaming

## Data Notes

- All user data (highlights, notes, vocabulary, AI provider configs) is stored in `data.db` in the project root
- The app automatically backs up the database to `backup/` on exit
- Exported vocabulary files are saved in `vocab/`

> ⚠️ This is a local single-user tool. API Keys are stored in plain text in the local SQLite database. Do not share your database file.

## Contributing

Issues and PRs are welcome!

## License

[MIT](LICENSE)
