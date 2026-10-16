"""
Annotation popups: edit (QDialog) and view (QToolTip) implementations.
Uses Qt's built-in systems for maximum reliability.
"""
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QLabel,
    QPushButton, QFrame
)
from PySide6.QtGui import QColor, QCursor, QTextCursor
from PySide6.QtWidgets import QToolTip

from core.theme_colors import get_theme_colors


class AnnotationTextEdit(QTextEdit):
    """Text editor with eight-space indentation and block indent shortcuts."""

    INDENT_WIDTH = 8
    INDENT = " " * INDENT_WIDTH

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * self.INDENT_WIDTH)

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()
        is_tab = key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab)
        has_disallowed_modifier = modifiers & (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        )
        if is_tab and not has_disallowed_modifier:
            unindent = key == Qt.Key.Key_Backtab or bool(
                modifiers & Qt.KeyboardModifier.ShiftModifier
            )
            self._change_indent(unindent)
            event.accept()
            return
        super().keyPressEvent(event)

    def _change_indent(self, unindent: bool):
        """Indent selected lines together, or adjust the current line."""
        cursor = self.textCursor()
        anchor = cursor.anchor()
        position = cursor.position()
        selection_start = min(anchor, position)
        selection_end = max(anchor, position)
        has_selection = anchor != position
        blocks = (
            self._selected_blocks(selection_start, selection_end)
            if has_selection
            else [cursor.block()]
        )

        edits = []
        if not has_selection and not unindent:
            # With no selection, Tab behaves like a normal text insertion at
            # the caret. Shift+Tab still removes indentation from the line.
            edits.append((position, self.INDENT_WIDTH))

        for block in blocks:
            if not has_selection and not unindent:
                break
            block_pos = block.position()
            if unindent:
                line_text = block.text()
                remove_count = 0
                while remove_count < self.INDENT_WIDTH and remove_count < len(line_text):
                    if line_text[remove_count] == " ":
                        remove_count += 1
                    else:
                        break
                if remove_count == 0 and line_text.startswith("\t"):
                    remove_count = 1
                if remove_count:
                    edits.append((block_pos, remove_count))
            else:
                edits.append((block_pos, self.INDENT_WIDTH))

        if not edits:
            return

        document = self.document()
        edit_cursor = QTextCursor(document)
        edit_cursor.beginEditBlock()
        for block_pos, amount in reversed(edits):
            edit_cursor.setPosition(block_pos)
            if unindent:
                edit_cursor.movePosition(
                    QTextCursor.MoveOperation.NextCharacter,
                    QTextCursor.MoveMode.KeepAnchor,
                    amount,
                )
                edit_cursor.removeSelectedText()
            else:
                edit_cursor.insertText(self.INDENT)
        edit_cursor.endEditBlock()

        def adjusted_position(original: int, include_equal: bool = False) -> int:
            adjusted = original
            for block_pos, amount in edits:
                applies = block_pos < original or (include_equal and block_pos == original)
                if applies:
                    adjusted += amount if not unindent else -amount
            return max(0, adjusted)

        if has_selection:
            new_anchor = adjusted_position(anchor)
            new_position = adjusted_position(position)
        else:
            new_anchor = adjusted_position(anchor, include_equal=not unindent)
            new_position = adjusted_position(position, include_equal=not unindent)

        new_cursor = QTextCursor(document)
        new_cursor.setPosition(new_anchor)
        new_cursor.setPosition(new_position, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(new_cursor)

    def _selected_blocks(self, selection_start: int, selection_end: int):
        """Return every text block touched by a selection."""
        document = self.document()
        start_cursor = QTextCursor(document)
        start_cursor.setPosition(selection_start)
        first_block = start_cursor.block()

        end_cursor = QTextCursor(document)
        end_cursor.setPosition(max(selection_start, selection_end - 1))
        last_block = end_cursor.block()

        blocks = []
        block = first_block
        while block.isValid():
            blocks.append(block)
            if block == last_block:
                break
            block = block.next()
        return blocks


class AnnotationEditPopup(QDialog):
    """Editable annotation dialog for writing/editing notes."""

    def __init__(self, annotation_id: int, initial_text: str = "", parent=None):
        super().__init__(parent)
        self.annotation_id = annotation_id
        self.result_text = None
        self.result_delete = False

        self.setWindowTitle("📝 Annotation")
        self.setMinimumWidth(320)
        self.setMaximumWidth(450)
        self.setModal(False)

        colors = get_theme_colors()
        bg = colors.get("bg", "#2b2b2b")
        text_c = colors.get("text", "#eeeeee")
        border = colors.get("border", "#555555")
        input_bg = colors.get("input_bg", bg)

        self.setStyleSheet(
            f"QDialog {{ background: {bg}; }}"
            f"QTextEdit {{ background: {input_bg}; color: {text_c}; "
            f"border: 1px solid {border}; border-radius: 4px; padding: 6px; }}"
            f"QPushButton {{ background: {colors.get('hover', '#444444')}; color: {text_c}; "
            f"border: none; border-radius: 4px; padding: 6px 14px; min-width: 70px; }}"
            f"QPushButton:hover {{ background: {colors.get('selected', '#3a5a8a')}; }}"
            f"QLabel {{ color: {text_c}; background: transparent; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel("📝 Annotation")
        header.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(header)

        self.text_edit = AnnotationTextEdit()
        self.text_edit.setPlainText(initial_text)
        self.text_edit.setMinimumHeight(100)
        self.text_edit.setMaximumHeight(220)
        layout.addWidget(self.text_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_save = QPushButton("💾 Save")
        self.btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(self.btn_save)

        self.btn_delete = QPushButton("🗑️ Delete")
        self.btn_delete.clicked.connect(self._on_delete)
        btn_row.addWidget(self.btn_delete)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)

        layout.addLayout(btn_row)

    def _on_save(self):
        self.result_text = self.text_edit.toPlainText().strip()
        self.accept()

    def _on_delete(self):
        self.result_delete = True
        self.accept()

    @staticmethod
    def edit_at(annotation_id: int, global_pos: QPoint, initial_text: str = "", parent=None) -> tuple:
        """Show the edit dialog at position. Returns (text, is_delete) or (None, False) if cancelled."""
        dlg = AnnotationEditPopup(annotation_id, initial_text, parent)
        # Position near the click point
        dlg.move(global_pos + QPoint(20, 20))
        result = dlg.exec()
        if result == QDialog.DialogCode.Accepted:
            return (dlg.result_text, dlg.result_delete)
        return (None, False)


class AnnotationViewPopup:
    """
    Read-only annotation tooltip placeholder.
    Actual display is handled by QLabel child widgets in widgets.py.
    """

    @staticmethod
    def show(text: str, global_pos: QPoint = None):
        """No-op - display handled by hover labels in widgets."""
        pass

    @staticmethod
    def hide():
        """No-op - hide handled by hover labels in widgets."""
        pass
