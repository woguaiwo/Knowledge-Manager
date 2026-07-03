"""
Target Reading left panel.
User asks a question about the whole PDF; the panel emits signals for
MainWindow to run AI analysis and highlight matching passages.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLabel, QComboBox, QSizePolicy
)

from core import database
from core.theme_colors import get_theme_colors


class TargetReadingPanel(QWidget):
    query_submitted = Signal(str)
    analysis_started = Signal()
    analysis_complete = Signal(list)
    analysis_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_provider = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Header
        header = QLabel("🎯 Target Reading")
        header.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(header)

        desc = QLabel(
            "Ask a question about the whole document. AI will find the most "
            "relevant passages and highlight them in the PDF."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 11px; color: #888888;")
        layout.addWidget(desc)

        # Provider selector
        provider_row = QHBoxLayout()
        provider_row.addWidget(QLabel("Provider:"))
        self.cmb_provider = QComboBox()
        self.cmb_provider.setMinimumWidth(120)
        self.cmb_provider.currentIndexChanged.connect(self._on_provider_changed)
        provider_row.addWidget(self.cmb_provider, 1)
        layout.addLayout(provider_row)

        # Question input
        self.edit_question = QTextEdit()
        self.edit_question.setPlaceholderText(
            "e.g. What explanations did the author give about ...?"
        )
        self.edit_question.setMaximumHeight(120)
        self.edit_question.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.edit_question)

        # Send button
        self.btn_send = QPushButton("🔍 Find Relevant Passages")
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.clicked.connect(self._on_send)
        layout.addWidget(self.btn_send)

        # Status / result display
        self.lbl_status = QLabel("Ready")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("font-size: 11px; color: #888888;")
        layout.addWidget(self.lbl_status)

        self.result_display = QTextEdit()
        self.result_display.setReadOnly(True)
        self.result_display.setPlaceholderText("AI analysis results will appear here...")
        self.result_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.result_display)

        layout.addStretch()

        self._refresh_providers()
        self.apply_theme()

    # ------------------------------------------------------------------ #
    #  Provider
    # ------------------------------------------------------------------ #
    def _refresh_providers(self):
        self.cmb_provider.clear()
        providers = database.get_all_ai_providers()
        default_id = None
        for p in providers:
            display = f"{p['name']} {'(default)' if p.get('is_default') else ''}"
            self.cmb_provider.addItem(display, p["id"])
            if p.get("is_default"):
                default_id = p["id"]
        if default_id is not None:
            idx = self.cmb_provider.findData(default_id)
            if idx >= 0:
                self.cmb_provider.setCurrentIndex(idx)
        self._on_provider_changed(self.cmb_provider.currentIndex())

    def _on_provider_changed(self, index: int):
        if index < 0:
            self._current_provider = None
            return
        provider_id = self.cmb_provider.itemData(index)
        self._current_provider = database.get_ai_provider(provider_id)

    def current_provider(self):
        return self._current_provider

    # ------------------------------------------------------------------ #
    #  Actions
    # ------------------------------------------------------------------ #
    def _on_send(self):
        text = self.edit_question.toPlainText().strip()
        if not text:
            return
        if not self._current_provider:
            self.lbl_status.setText("⚠️ No AI provider selected.")
            return
        if not self._current_provider.get("api_key"):
            self.lbl_status.setText("⚠️ API Key not configured.")
            return
        self.query_submitted.emit(text)

    def set_analyzing(self, analyzing: bool):
        self.btn_send.setEnabled(not analyzing)
        self.edit_question.setEnabled(not analyzing)
        if analyzing:
            self.lbl_status.setText("Analyzing document, please wait...")
            self.result_display.clear()
        else:
            self.lbl_status.setText("Analysis complete.")

    def append_result(self, text: str):
        self.result_display.append(text)

    def set_error(self, message: str):
        self.lbl_status.setText(f"Error: {message}")
        self.set_analyzing(False)

    # ------------------------------------------------------------------ #
    #  Theme
    # ------------------------------------------------------------------ #
    def apply_theme(self, theme_name: str = None):
        colors = get_theme_colors(theme_name)
        bg = colors.get("bg", "#2b2b2b")
        text = colors.get("text", "#eeeeee")
        border = colors.get("border", "#555555")
        self.setStyleSheet(
            f"QWidget {{ background: {bg}; color: {text}; }}"
            f"QTextEdit {{ background: {colors.get('base', '#1e1e1e')}; color: {text}; "
            f"border: 1px solid {border}; border-radius: 4px; padding: 6px; }}"
            f"QComboBox {{ background: {colors.get('base', '#1e1e1e')}; color: {text}; "
            f"border: 1px solid {border}; padding: 4px; }}"
            f"QPushButton {{ background: {colors.get('btn_bg', '#3a3a3a')}; color: {text}; "
            f"border: 1px solid {border}; padding: 6px 12px; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {colors.get('btn_hover', '#4a4a4a')}; }}"
            f"QLabel {{ color: {text}; }}"
        )
