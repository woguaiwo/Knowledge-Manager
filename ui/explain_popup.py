"""
Floating popup widget for Explain Mode.
Appears near the cursor and shows AI explanations with follow-up input.
Supports Markdown rendering, user-resizable, theme-aware, click-outside-to-close,
and streaming text display.
"""
from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtGui import QCursor, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit,
    QPushButton, QLabel, QSizePolicy, QSizeGrip, QApplication
)

from core import database
from ui.theme_manager import THEMES


class ExplainPopup(QWidget):
    """
    Frameless floating popup for AI explanations.
    Non-modal; user can continue interacting with the PDF.
    Supports Markdown rendering, resize via QSizeGrip, theme adaptation,
    click-outside-to-close, and streaming text display.
    """
    follow_up_requested = Signal(str)   # text to send as follow-up
    save_requested = Signal(str, str)   # word, latest_response
    closed = Signal()                   # user clicked Close or clicked outside

    def __init__(self, current_word: str = "", parent=None):
        super().__init__(parent)
        self.current_word = current_word
        self.latest_response = ""
        self._dragging = False
        self._drag_start_pos = None
        self._streaming = False
        self._stream_buffer = ""
        self.is_pinned = False

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMinimumWidth(480)
        self.setMinimumHeight(340)
        self.resize(520, 400)

        # Main container with border and background
        self.container = QWidget(self)
        self.container.setObjectName("ExplainPopupContainer")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.container)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(10, 10, 10, 10)
        container_layout.setSpacing(8)

        # Header
        self.lbl_header = QLabel(f"🤖 AI Explanation — {current_word[:30]}{'...' if len(current_word) > 30 else ''}")
        container_layout.addWidget(self.lbl_header)

        # Conversation display (Markdown-capable)
        self.text_display = QTextEdit()
        self.text_display.setReadOnly(True)
        self.text_display.setPlaceholderText("Thinking...")
        self.text_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        container_layout.addWidget(self.text_display)

        # Follow-up input
        input_layout = QHBoxLayout()
        self.edit_followup = QLineEdit()
        self.edit_followup.setPlaceholderText("Ask a follow-up question...")
        self.btn_send = QPushButton("Send")
        input_layout.addWidget(self.edit_followup)
        input_layout.addWidget(self.btn_send)
        container_layout.addLayout(input_layout)

        # Action buttons + resize grip
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_pin = QPushButton("📌")
        self.btn_pin.setCheckable(True)
        self.btn_pin.setToolTip("Pin (prevent auto-close)")
        self.btn_pin.setFixedWidth(40)
        self.btn_save = QPushButton("💾 Save")
        self.btn_close = QPushButton("Close")
        btn_layout.addWidget(self.btn_pin)
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_close)
        btn_layout.addWidget(QSizeGrip(self.container), alignment=Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        container_layout.addLayout(btn_layout)

        self.setLayout(layout)

        # Connections
        self.btn_send.clicked.connect(self._on_send)
        self.edit_followup.returnPressed.connect(self._on_send)
        self.btn_pin.toggled.connect(self._on_pin_toggled)
        self.btn_save.clicked.connect(self._on_save)
        self.btn_close.clicked.connect(self._on_close)

        # Apply current theme
        self.apply_theme(database.get_setting("theme", "dark"))

    # ------------------------------------------------------------------ #
    #  Theme
    # ------------------------------------------------------------------ #
    def apply_theme(self, theme_name: str):
        """Apply theme colors to the popup."""
        theme = THEMES.get(theme_name, THEMES["dark"])
        colors = theme.get("popup", {})
        bg = colors.get("bg", "#2d2d2d")
        base = colors.get("base", "#1e1e1e")
        text = colors.get("text", "#eeeeee")
        border = colors.get("border", "#555555")
        btn_bg = colors.get("btn_bg", "#3a3a3a")
        btn_hover = colors.get("btn_hover", "#4a4a4a")
        header = colors.get("header", "#ffffff")

        self.container.setStyleSheet(
            f"#ExplainPopupContainer {{"
            f"  background: {bg};"
            f"  border: 1px solid {border};"
            f"  border-radius: 8px;"
            f"}}"
            f"QTextEdit {{"
            f"  background: {base};"
            f"  color: {text};"
            f"  border: 1px solid {border};"
            f"  border-radius: 4px;"
            f"  padding: 6px;"
            f"}}"
            f"QLineEdit {{"
            f"  background: {base};"
            f"  color: {text};"
            f"  border: 1px solid {border};"
            f"  border-radius: 4px;"
            f"  padding: 4px;"
            f"}}"
            f"QPushButton {{"
            f"  background: {btn_bg};"
            f"  color: {text};"
            f"  border: 1px solid {border};"
            f"  border-radius: 4px;"
            f"  padding: 4px 10px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {btn_hover};"
            f"}}"
            f"QLabel {{"
            f"  color: {text};"
            f"  font-size: 11px;"
            f"}}"
        )
        self.lbl_header.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {header};")

    # ------------------------------------------------------------------ #
    #  Streaming display
    # ------------------------------------------------------------------ #
    def start_stream(self):
        """Prepare the display for streaming text."""
        self._streaming = True
        self._stream_buffer = ""
        self.text_display.setPlainText("")
        self.text_display.setPlaceholderText("")

    def append_stream_chunk(self, chunk: str):
        """Append a chunk of text during streaming. Scroll position is preserved."""
        if not self._streaming or not self.isVisible():
            return
        scrollbar = self.text_display.verticalScrollBar()
        old_value = scrollbar.value()

        self._stream_buffer += chunk
        # Use a document-level cursor so setTextCursor (which auto-scrolls) is not needed
        cursor = QTextCursor(self.text_display.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(chunk)

        scrollbar.setValue(old_value)

    def finish_stream(self):
        """Finalize streaming and render Markdown. Scroll position is preserved."""
        self._streaming = False
        scrollbar = self.text_display.verticalScrollBar()
        old_value = scrollbar.value()

        self.text_display.setMarkdown(self._stream_buffer)
        self.latest_response = self._stream_buffer

        scrollbar.setValue(old_value)

    # ------------------------------------------------------------------ #
    #  Text helpers
    # ------------------------------------------------------------------ #
    def set_text(self, text: str):
        self._streaming = False
        self.text_display.setMarkdown(text)
        self.latest_response = text

    def append_text(self, text: str):
        self._streaming = False
        scrollbar = self.text_display.verticalScrollBar()
        old_value = scrollbar.value()

        current = self.text_display.toMarkdown()
        if current and current.strip():
            self.text_display.setMarkdown(current + "\n\n---\n\n" + text)
        else:
            self.text_display.setMarkdown(text)
        self.latest_response = text

        scrollbar.setValue(old_value)

    def set_thinking(self, thinking: bool = True):
        if thinking:
            self.text_display.setPlaceholderText("Thinking...")
            if not self._streaming:
                self.text_display.setMarkdown("")
            self.btn_send.setEnabled(False)
            self.edit_followup.setEnabled(False)
        else:
            self.btn_send.setEnabled(True)
            self.edit_followup.setEnabled(True)
            self.edit_followup.setFocus()

    # ------------------------------------------------------------------ #
    #  Event handling (drag, click-outside-to-close)
    # ------------------------------------------------------------------ #
    def showEvent(self, event):
        super().showEvent(event)
        app = QApplication.instance()
        if app:
            app.installEventFilter(self)

    def hideEvent(self, event):
        super().hideEvent(event)
        app = QApplication.instance()
        if app:
            app.removeEventFilter(self)

    def eventFilter(self, watched, event):
        if self.is_pinned:
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.MouseButtonPress:
            if hasattr(event, 'globalPosition'):
                global_pos = event.globalPosition().toPoint()
            else:
                global_pos = event.globalPos()
            if not self.geometry().contains(global_pos):
                self.hide()
                self.closed.emit()
                return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.pos())
            if child in (None, self, self.container, self.lbl_header):
                self._dragging = True
                self._drag_start_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.move(event.globalPosition().toPoint() - self._drag_start_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging = False
        super().mouseReleaseEvent(event)

    def show_near_cursor(self, offset_x: int = 20, offset_y: int = 20):
        pos = QCursor.pos()
        x = pos.x() + offset_x
        y = pos.y() + offset_y

        screen = self.screen()
        if screen:
            geo = screen.availableGeometry()
            if x + self.width() > geo.right():
                x = pos.x() - self.width() - offset_x
            if y + self.height() > geo.bottom():
                y = pos.y() - self.height() - offset_y
            x = max(geo.left(), x)
            y = max(geo.top(), y)

        self.move(x, y)
        self.show()
        self.raise_()

    def _on_send(self):
        text = self.edit_followup.text().strip()
        if text:
            self.append_text(f"**[You]** {text}")
            self.edit_followup.clear()
            self.follow_up_requested.emit(text)
            self.set_thinking(True)

    def _on_save(self):
        self.save_requested.emit(self.current_word, self.latest_response)

    def _on_pin_toggled(self, checked: bool):
        self.is_pinned = checked
        if checked:
            self.btn_pin.setText("📍")
            self.btn_pin.setToolTip("Unpin")
        else:
            self.btn_pin.setText("📌")
            self.btn_pin.setToolTip("Pin (prevent auto-close)")

    def _on_close(self):
        self.closed.emit()
        self.hide()
