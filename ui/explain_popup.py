"""
Floating popup widget for Explain Mode.
Appears near the cursor and shows AI explanations with follow-up input.
Supports Markdown rendering, user-resizable, theme-aware, click-outside-to-close,
and streaming text display.
"""
from PySide6.QtCore import Qt, Signal, QEvent, QTimer
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
        # Keep network chunk handling cheap for the GUI thread.  Providers can
        # emit dozens of chunks per second; inserting each one into QTextEdit
        # forces a document layout/repaint for every signal and starves button
        # hover/pressed feedback.  Chunks are accumulated and flushed at a
        # modest cadence instead.
        self._stream_pending = ""
        self._stream_flush_timer = QTimer(self)
        self._stream_flush_timer.setSingleShot(True)
        self._stream_flush_timer.setInterval(40)
        self._stream_flush_timer.timeout.connect(self._flush_stream_buffer)
        self._hover_refresh_timer = QTimer(self)
        self._hover_refresh_timer.setInterval(50)
        self._hover_refresh_timer.timeout.connect(self._refresh_button_hover)
        self.is_pinned = False
        self._close_signal_emitted = False
        # The page location that should receive an annotation when Save is clicked.
        self.annotation_page_number = None
        self.annotation_global_pos = None
        self.saved_annotation_id = None

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
        self._save_button_default_text = self.btn_save.text()
        self.btn_close = QPushButton("Close")
        for button in (self.btn_pin, self.btn_save, self.btn_close):
            # Keep hover/pressed feedback responsive while the stream is
            # updating the text area.
            button.setMouseTracking(True)
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
            f"QPushButton[manualHover=\"true\"] {{"
            f"  background: {btn_hover};"
            f"}}"
            f"QPushButton:pressed {{"
            f"  background: {btn_hover};"
            f"  border: 1px solid {header};"
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
        self._stop_stream_refresh()
        self._streaming = True
        self._stream_buffer = ""
        self._stream_pending = ""
        self.latest_response = ""
        self.text_display.setPlainText("")
        self.text_display.setPlaceholderText("")

    def append_stream_chunk(self, chunk: str):
        """Queue a chunk of text during streaming.

        The actual QTextEdit update is throttled by ``_stream_flush_timer`` so
        a fast SSE stream does not monopolize the GUI event loop.
        """
        if not self._streaming or not self.isVisible():
            return
        if not chunk:
            return
        self._stream_buffer += chunk
        self._stream_pending += chunk
        if not self._stream_flush_timer.isActive():
            self._stream_flush_timer.start()

    def _flush_stream_buffer(self):
        """Insert queued streaming text in one document update."""
        pending = self._stream_pending
        if not pending:
            return
        self._stream_pending = ""

        scrollbar = self.text_display.verticalScrollBar()
        old_value = scrollbar.value()
        # Use a document-level cursor so setTextCursor (which auto-scrolls) is
        # not needed and the user's current scroll position is preserved.
        cursor = QTextCursor(self.text_display.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(pending)
        scrollbar.setValue(old_value)

    def _stop_stream_refresh(self):
        """Stop pending GUI refresh work and release queued chunk text."""
        if self._stream_flush_timer.isActive():
            self._stream_flush_timer.stop()
        self._stream_pending = ""

    def finish_stream(self):
        """Finalize streaming and render Markdown. Scroll position is preserved."""
        self._stop_stream_refresh()
        # Flush before switching to Markdown so the final timer interval is
        # never lost when the worker's result arrives immediately afterwards.
        # ``_stop_stream_refresh`` clears the pending buffer, so retain the
        # queued value through a small local handoff when needed.
        # (The pending text is normally already flushed by the timer.)
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
        self._stop_stream_refresh()
        self._streaming = False
        self._stream_buffer = ""
        self.text_display.setMarkdown(text)
        self.latest_response = text

    def append_text(self, text: str):
        # If called while a stream is active, commit the queued raw text first
        # so appending a status/error message cannot silently drop the last
        # interval of the response.
        if self._streaming:
            self._stream_flush_timer.stop()
            self._flush_stream_buffer()
        else:
            self._stop_stream_refresh()
        self._streaming = False
        self._stream_buffer = ""
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

    def prepare_follow_up_save(self):
        """Make the next response save as a new annotation.

        A follow-up belongs to the same conversation, but it is a separate
        piece of knowledge.  Clearing the previous id prevents the Save
        handler from treating the next response as an update.
        """
        self.saved_annotation_id = None
        self.btn_save.setText(self._save_button_default_text)
        self.btn_save.setToolTip("Save this explanation as a new annotation")

    # ------------------------------------------------------------------ #
    #  Event handling (drag, click-outside-to-close)
    # ------------------------------------------------------------------ #
    def showEvent(self, event):
        super().showEvent(event)
        app = QApplication.instance()
        if app:
            app.installEventFilter(self)
        self._refresh_button_hover()
        self._hover_refresh_timer.start()

    def hideEvent(self, event):
        self._hover_refresh_timer.stop()
        self._stop_stream_refresh()
        self._streaming = False
        self._stream_buffer = ""
        super().hideEvent(event)
        app = QApplication.instance()
        if app:
            app.removeEventFilter(self)

    def eventFilter(self, watched, event):
        if self.is_pinned:
            return False
        if event.type() == QEvent.Type.MouseButtonPress:
            if hasattr(event, 'globalPosition'):
                global_pos = event.globalPosition().toPoint()
            else:
                global_pos = event.globalPos()
            if not self.geometry().contains(global_pos):
                self.hide()
                if not self._close_signal_emitted:
                    self._close_signal_emitted = True
                    self.closed.emit()
                return True
        # Do not let the popup's application-level outside-click watcher
        # participate in ordinary hover/move dispatch.
        return False

    def _refresh_button_hover(self):
        """Synchronize button hover styling even for an inactive Tool window."""
        global_pos = QCursor.pos()
        for button in (self.btn_pin, self.btn_save, self.btn_close):
            hovered = button.isVisible() and button.rect().contains(
                button.mapFromGlobal(global_pos)
            )
            previous = button.property("manualHover") is True
            if hovered == previous:
                continue
            button.setProperty("manualHover", hovered)
            style = button.style()
            style.unpolish(button)
            style.polish(button)
            button.update()

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
        self._close_signal_emitted = False
        self.show()
        self.raise_()
        # A Tool window can be visible and clickable on Windows without being
        # the active window.  In that state Qt delays hover/pressed painting
        # until the first focus-changing action (such as Pin or completion
        # focusing the follow-up field).  Activate it immediately so controls
        # provide feedback from the moment the popup appears.
        self.activateWindow()

    def _on_send(self):
        text = self.edit_followup.text().strip()
        if text:
            self.append_text(f"**[You]** {text}")
            self.edit_followup.clear()
            self.follow_up_requested.emit(text)
            self.set_thinking(True)

    def _on_save(self):
        # A streamed response is not complete yet.  Ignore clicks during this
        # interval so a partial answer cannot be persisted as an annotation.
        # Keep the button visible as Save; once finish_stream() runs the same
        # button becomes active without changing its label.
        if self._streaming or not self.latest_response.strip():
            return
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
        # Hide first so the window disappears even if a connected slot needs
        # to detach a still-running network worker.  The old ordering emitted
        # ``closed`` before hiding, which made a blocked provider appear to
        # freeze the Close button.
        self.hide()
        if not self._close_signal_emitted:
            self._close_signal_emitted = True
            self.closed.emit()
