"""
Theme manager providing palettes and stylesheets for multiple themes.
"""
from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt

THEMES = {
    "dark": {
        "name": "Dark",
        "popup": {
            "bg": "#2d2d2d",
            "base": "#1e1e1e",
            "text": "#eeeeee",
            "border": "#555555",
            "btn_bg": "#3a3a3a",
            "btn_hover": "#4a4a4a",
            "header": "#ffffff",
        },
        "palette": {
            QPalette.ColorRole.Window: QColor(43, 43, 43),
            QPalette.ColorRole.WindowText: QColor(238, 238, 238),
            QPalette.ColorRole.Base: QColor(30, 30, 30),
            QPalette.ColorRole.AlternateBase: QColor(43, 43, 43),
            QPalette.ColorRole.ToolTipBase: QColor(238, 238, 238),
            QPalette.ColorRole.ToolTipText: QColor(238, 238, 238),
            QPalette.ColorRole.Text: QColor(238, 238, 238),
            QPalette.ColorRole.Button: QColor(53, 53, 53),
            QPalette.ColorRole.ButtonText: QColor(238, 238, 238),
            QPalette.ColorRole.Highlight: QColor(42, 130, 218),
            QPalette.ColorRole.HighlightedText: QColor(255, 255, 255),
        },
        "qss": """
            QMainWindow, QWidget { background: #2b2b2b; color: #eeeeee; }
            QToolBar { background: #333333; border: none; padding: 4px; }
            QToolButton { color: #eeeeee; padding: 6px 12px; background: transparent; border: none; }
            QToolButton:hover { background: #444444; border-radius: 4px; }
            QToolButton:checked { background: #3a5a8a; border-radius: 4px; }
            QToolButton:checked:hover { background: #4a6aaa; border-radius: 4px; }
            QDockWidget::title { background: #333333; padding: 6px; text-align: center; }
            QTableWidget { gridline-color: #555555; background: #1e1e1e; color: #eeeeee; border: none; }
            QHeaderView::section { background: #444444; color: #eeeeee; padding: 4px; border: 1px solid #555555; }
            QPushButton { background: #444444; color: #eeeeee; border: 1px solid #555555; padding: 6px 12px; border-radius: 4px; }
            QPushButton:hover { background: #555555; }
            QLineEdit { background: #1e1e1e; color: #eeeeee; border: 1px solid #555555; padding: 4px; border-radius: 3px; }
            QTextEdit { background: #1e1e1e; color: #eeeeee; border: 1px solid #555555; border-radius: 3px; }
            QScrollArea { border: none; background: #2b2b2b; }
            QLabel { color: #eeeeee; }
            QDialog { background: #2b2b2b; }
            QMenuBar { background: #333333; color: #eeeeee; }
            QMenuBar::item:selected { background: #444444; }
            QMenu { background: #333333; color: #eeeeee; border: 1px solid #555555; }
            QMenu::item:selected { background: #444444; }
            QComboBox { background: #1e1e1e; color: #eeeeee; border: 1px solid #555555; padding: 4px; }
            QComboBox QAbstractItemView { background: #1e1e1e; color: #eeeeee; selection-background-color: #2a82da; }
            QDockWidget::close-button, QDockWidget::float-button { padding: 6px; icon-size: 20px; }
            QTabBar::tab { min-width: 120px; max-width: 260px; padding: 5px 12px; }
            QSplitter::handle { background: #666666; }
        """
    },
    "light": {
        "name": "Light Minimal",
        "popup": {
            "bg": "#ffffff",
            "base": "#f5f5f5",
            "text": "#222222",
            "border": "#cccccc",
            "btn_bg": "#e0e0e0",
            "btn_hover": "#d0d0d0",
            "header": "#222222",
        },
        "palette": {
            QPalette.ColorRole.Window: QColor(245, 245, 245),
            QPalette.ColorRole.WindowText: QColor(34, 34, 34),
            QPalette.ColorRole.Base: QColor(255, 255, 255),
            QPalette.ColorRole.AlternateBase: QColor(240, 240, 240),
            QPalette.ColorRole.ToolTipBase: QColor(34, 34, 34),
            QPalette.ColorRole.ToolTipText: QColor(245, 245, 245),
            QPalette.ColorRole.Text: QColor(34, 34, 34),
            QPalette.ColorRole.Button: QColor(224, 224, 224),
            QPalette.ColorRole.ButtonText: QColor(34, 34, 34),
            QPalette.ColorRole.Highlight: QColor(0, 120, 212),
            QPalette.ColorRole.HighlightedText: QColor(255, 255, 255),
        },
        "qss": """
            QMainWindow, QWidget { background: #f5f5f5; color: #222222; }
            QToolBar { background: #eaeaea; border: none; padding: 4px; }
            QToolButton { color: #222222; padding: 6px 12px; background: transparent; border: none; }
            QToolButton:hover { background: #dcdcdc; border-radius: 4px; }
            QToolButton:checked { background: #a0c4ff; border-radius: 4px; }
            QToolButton:checked:hover { background: #90b4ef; border-radius: 4px; }
            QDockWidget::title { background: #eaeaea; padding: 6px; text-align: center; color: #222222; }
            QTableWidget { gridline-color: #cccccc; background: #ffffff; color: #222222; border: 1px solid #cccccc; }
            QHeaderView::section { background: #eaeaea; color: #222222; padding: 4px; border: 1px solid #cccccc; }
            QPushButton { background: #e0e0e0; color: #222222; border: 1px solid #cccccc; padding: 6px 12px; border-radius: 4px; }
            QPushButton:hover { background: #d0d0d0; }
            QLineEdit { background: #ffffff; color: #222222; border: 1px solid #cccccc; padding: 4px; border-radius: 3px; }
            QTextEdit { background: #ffffff; color: #222222; border: 1px solid #cccccc; border-radius: 3px; }
            QScrollArea { border: none; background: #f5f5f5; }
            QLabel { color: #222222; }
            QDialog { background: #f5f5f5; }
            QMenuBar { background: #eaeaea; color: #222222; }
            QMenuBar::item:selected { background: #dcdcdc; }
            QMenu { background: #ffffff; color: #222222; border: 1px solid #cccccc; }
            QMenu::item:selected { background: #e0e0e0; }
            QComboBox { background: #ffffff; color: #222222; border: 1px solid #cccccc; padding: 4px; }
            QComboBox QAbstractItemView { background: #ffffff; color: #222222; selection-background-color: #0078d4; }
            QDockWidget::close-button, QDockWidget::float-button { padding: 6px; icon-size: 20px; }
            QTabBar::tab { min-width: 120px; max-width: 260px; padding: 5px 12px; }
            QSplitter::handle { background: #999999; }
        """
    },
    "nature": {
        "name": "Nature Green",
        "popup": {
            "bg": "#f4f7f2",
            "base": "#ffffff",
            "text": "#2f3e2f",
            "border": "#b8d0b0",
            "btn_bg": "#d4e4cc",
            "btn_hover": "#c4d8bc",
            "header": "#2f3e2f",
        },
        "palette": {
            QPalette.ColorRole.Window: QColor(244, 247, 242),
            QPalette.ColorRole.WindowText: QColor(47, 62, 47),
            QPalette.ColorRole.Base: QColor(255, 255, 255),
            QPalette.ColorRole.AlternateBase: QColor(238, 245, 234),
            QPalette.ColorRole.ToolTipBase: QColor(47, 62, 47),
            QPalette.ColorRole.ToolTipText: QColor(244, 247, 242),
            QPalette.ColorRole.Text: QColor(47, 62, 47),
            QPalette.ColorRole.Button: QColor(212, 228, 204),
            QPalette.ColorRole.ButtonText: QColor(47, 62, 47),
            QPalette.ColorRole.Highlight: QColor(90, 143, 75),
            QPalette.ColorRole.HighlightedText: QColor(255, 255, 255),
        },
        "qss": """
            QMainWindow, QWidget { background: #f4f7f2; color: #2f3e2f; }
            QToolBar { background: #e4ede0; border: none; padding: 4px; }
            QToolButton { color: #2f3e2f; padding: 6px 12px; background: transparent; border: none; }
            QToolButton:hover { background: #d4e4cc; border-radius: 4px; }
            QToolButton:checked { background: #8fb880; border-radius: 4px; }
            QToolButton:checked:hover { background: #7fa870; border-radius: 4px; }
            QDockWidget::title { background: #e4ede0; padding: 6px; text-align: center; color: #2f3e2f; }
            QTableWidget { gridline-color: #c8d8c0; background: #ffffff; color: #2f3e2f; border: 1px solid #c8d8c0; }
            QHeaderView::section { background: #e4ede0; color: #2f3e2f; padding: 4px; border: 1px solid #c8d8c0; }
            QPushButton { background: #d4e4cc; color: #2f3e2f; border: 1px solid #b8d0b0; padding: 6px 12px; border-radius: 4px; }
            QPushButton:hover { background: #c4d8bc; }
            QLineEdit { background: #ffffff; color: #2f3e2f; border: 1px solid #b8d0b0; padding: 4px; border-radius: 3px; }
            QTextEdit { background: #ffffff; color: #2f3e2f; border: 1px solid #b8d0b0; border-radius: 3px; }
            QScrollArea { border: none; background: #f4f7f2; }
            QLabel { color: #2f3e2f; }
            QDialog { background: #f4f7f2; }
            QMenuBar { background: #e4ede0; color: #2f3e2f; }
            QMenuBar::item:selected { background: #d4e4cc; }
            QMenu { background: #ffffff; color: #2f3e2f; border: 1px solid #c8d8c0; }
            QMenu::item:selected { background: #d4e4cc; }
            QComboBox { background: #ffffff; color: #2f3e2f; border: 1px solid #b8d0b0; padding: 4px; }
            QComboBox QAbstractItemView { background: #ffffff; color: #2f3e2f; selection-background-color: #5a8f4b; }
            QDockWidget::close-button, QDockWidget::float-button { padding: 6px; icon-size: 20px; }
            QTabBar::tab { min-width: 120px; max-width: 260px; padding: 5px 12px; }
            QSplitter::handle { background: #88a880; }
        """
    }
}


def apply_theme(app, theme_name: str):
    """Apply a named theme to the QApplication instance."""
    theme = THEMES.get(theme_name, THEMES["dark"])
    palette = QPalette()
    for role, color in theme["palette"].items():
        palette.setColor(role, color)
    app.setPalette(palette)
    app.setStyle("Fusion")
    app.setStyleSheet(theme["qss"])
