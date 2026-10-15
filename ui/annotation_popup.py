"""
Annotation popups: edit (QDialog) and view (QToolTip) implementations.
Uses Qt's built-in systems for maximum reliability.
"""
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QLabel,
    QPushButton, QFrame
)
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import QToolTip

from core.theme_colors import get_theme_colors


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

        self.text_edit = QTextEdit()
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
    Read-only annotation tooltip using QToolTip.
    Follows cursor position automatically.
    """

    @staticmethod
    def show(text: str, global_pos: QPoint = None):
        """Show tooltip at cursor position (or given position)."""
        if not global_pos:
            global_pos = QCursor.pos()
        display_text = text if text else "(No note)"
        # QToolTip handles positioning and styling natively
        QToolTip.showText(global_pos + QPoint(16, 16), display_text)

    @staticmethod
    def hide():
        """Hide the tooltip."""
        QToolTip.hideText()
