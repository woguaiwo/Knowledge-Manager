"""
Right-side panel for per-page note taking.
Notes are automatically saved to SQLite and indexed by (pdf_path, page_number).
Plain-text only: fast, lightweight, draft-style note-taking.
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontMetrics, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLabel,
    QCheckBox, QSizePolicy
)

from core import database


class NoteEditor(QTextEdit):
    """
    Custom QTextEdit that supports:
    - Multi-line indent with Tab / outdent with Shift+Tab
    - Auto horizontal rule on '---' + Enter (plain-text dashes)
    """

    def keyPressEvent(self, event):
        # Enter after '---': insert plain-text separator line
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            cursor = self.textCursor()
            if cursor.block().text().strip() == '---':
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                cursor.removeSelectedText()
                # Compute width in characters based on viewport width
                metrics = QFontMetrics(self.font())
                char_width = max(1, metrics.horizontalAdvance('-'))
                available = max(self.viewport().width() - 20, 200)
                count = max(30, available // char_width)
                cursor.insertText('-' * count)
                cursor.insertBlock()
                self.setTextCursor(cursor)
                return

        if event.key() == Qt.Key.Key_Tab:
            cursor = self.textCursor()
            if cursor.hasSelection():
                start = cursor.selectionStart()
                end = cursor.selectionEnd()

                temp = QTextCursor(cursor)
                temp.setPosition(start)
                temp.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                block_start = temp.position()

                temp.setPosition(end)
                temp.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                block_end = temp.position()

                temp.setPosition(block_start)
                temp.setPosition(block_end, QTextCursor.MoveMode.KeepAnchor)
                text = temp.selectedText()

                if '\u2029' in text:
                    lines = text.split('\u2029')
                    if lines and lines[-1] == '':
                        lines.pop()
                    indented = '\u2029'.join('\t' + line for line in lines)
                    temp.insertText(indented)
                    new_end = temp.position()
                    temp.setPosition(block_start + 1)
                    temp.setPosition(new_end, QTextCursor.MoveMode.KeepAnchor)
                    self.setTextCursor(temp)
                    return
                else:
                    cursor.insertText('\t')
                    return
            cursor.insertText('\t')
            return

        elif event.key() == Qt.Key.Key_Backtab or \
             (event.key() == Qt.Key.Key_Tab and event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            cursor = self.textCursor()
            if cursor.hasSelection():
                start = cursor.selectionStart()
                end = cursor.selectionEnd()

                temp = QTextCursor(cursor)
                temp.setPosition(start)
                temp.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                block_start = temp.position()

                temp.setPosition(end)
                temp.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                block_end = temp.position()

                temp.setPosition(block_start)
                temp.setPosition(block_end, QTextCursor.MoveMode.KeepAnchor)
                text = temp.selectedText()

                if '\u2029' in text:
                    lines = text.split('\u2029')
                    if lines and lines[-1] == '':
                        lines.pop()
                    outdented = []
                    for line in lines:
                        if line.startswith('\t'):
                            outdented.append(line[1:])
                        else:
                            outdented.append(line)
                    temp.insertText('\u2029'.join(outdented))
                    new_end = temp.position()
                    temp.setPosition(block_start)
                    temp.setPosition(new_end, QTextCursor.MoveMode.KeepAnchor)
                    self.setTextCursor(temp)
                    return
                else:
                    text = cursor.selectedText()
                    if text.startswith('\t'):
                        cursor.insertText(text[1:])
                    return
            else:
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.setPosition(cursor.position() + 1, QTextCursor.MoveMode.KeepAnchor)
                if cursor.selectedText() == '\t':
                    cursor.insertText('')
                return

        super().keyPressEvent(event)


class NotePanel(QWidget):
    """
    Panel for taking notes on individual PDF pages.
    Plain-text only: fast auto-follow, auto-save after 1s debounce.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_pdf_path = ""
        self.page_count = 0
        self.current_page = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Header row: page info + follow checkbox
        header = QHBoxLayout()
        self.lbl_page = QLabel("Page: -")
        self.lbl_page.setStyleSheet("font-size: 13px; font-weight: bold;")
        header.addWidget(self.lbl_page)
        header.addStretch()
        self.chk_follow = QCheckBox("Follow current page")
        self.chk_follow.setChecked(True)
        header.addWidget(self.chk_follow)
        layout.addLayout(header)

        # Note editor
        self.editor = NoteEditor()
        self.editor.setPlaceholderText("Take notes for this page...")
        self.editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        metrics = QFontMetrics(self.editor.font())
        self.editor.setTabStopDistance(metrics.horizontalAdvance(' ') * 8)
        layout.addWidget(self.editor)

        # Status label
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("font-size: 11px; color: #888888;")
        layout.addWidget(self.lbl_status)

        self.setLayout(layout)

        # Auto-save timer (1s debounce)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_current_note)
        self.editor.textChanged.connect(self._on_text_changed)

    def set_pdf(self, pdf_path: str, page_count: int = 0, page_number: int = 0):
        """Bind to a new PDF document. If the same PDF, only update page_count and page_number."""
        if self.current_pdf_path == pdf_path:
            self.page_count = page_count
            if page_number != self.current_page:
                self._save_current_note()
                self.current_page = page_number
                self._load_note(page_number)
            return
        self._save_current_note()
        self.current_pdf_path = pdf_path
        self.page_count = page_count
        self.current_page = page_number
        self._load_note(page_number)

    def on_page_changed(self, page_number: int):
        """Called when PDF scrolls to a different primary page."""
        if not self.chk_follow.isChecked():
            return
        if page_number == self.current_page:
            return
        self._save_current_note()
        self.current_page = page_number
        self._load_note(page_number)

    def _load_note(self, page_number: int):
        """Load note content for the given page."""
        self.lbl_page.setText(f"Page: {page_number + 1}")
        note = database.get_page_note(self.current_pdf_path, page_number) if self.current_pdf_path else ""
        self.editor.blockSignals(True)
        self.editor.setPlainText(note or "")
        self.editor.blockSignals(False)
        self.lbl_status.setText("")

    def _on_text_changed(self):
        self.lbl_status.setText("Unsaved...")
        self._save_timer.start(1000)

    def _save_current_note(self):
        """Persist current editor content to database."""
        if not self.current_pdf_path:
            return
        content = self.editor.toPlainText()
        database.save_page_note(self.current_pdf_path, self.current_page, content)
        self.lbl_status.setText("Saved")
