"""
Annotation popups: edit (writable) and view (read-only) floating windows.
"""
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLabel,
    QPushButton, QFrame
)
from PySide6.QtGui import QColor

from core.theme_colors import get_theme_colors


class AnnotationEditPopup(QFrame):
    """Editable annotation popup for writing/editing notes."""

    save_requested = Signal(int, str)  # annotation_id, text
    delete_requested = Signal(int)     # annotation_id
    closed = Signal()

    def __init__(self, annotation_id: int, initial_text: str = "", parent=None):
        super().__init__(parent)
        self.annotation_id = annotation_id
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.setMinimumWidth(280)
        self.setMaximumWidth(400)

        container = QFrame(self)
        colors = get_theme_colors()
        bg = colors.get("bg", "#2b2b2b")
        text_c = colors.get("text", "#eeeeee")
        border = colors.get("border", "#555555")

        container.setStyleSheet(
            f"QFrame {{ background: {bg}; border: 1px solid {border}; border-radius: 8px; }}"
            f"QTextEdit {{ background: {colors.get('input_bg', bg)}; color: {text_c}; "
            f"border: 1px solid {border}; border-radius: 4px; padding: 6px; }}"
            f"QPushButton {{ background: {colors.get('hover', '#444444')}; color: {text_c}; "
            f"border: none; border-radius: 4px; padding: 6px 14px; }}"
            f"QPushButton:hover {{ background: {colors.get('selected', '#3a5a8a')}; }}"
            f"QLabel {{ color: {text_c}; }}"
        )

        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QLabel("📝 Annotation")
        header.setStyleSheet("font-weight: bold; font-size: 13px; border: none;")
        layout.addWidget(header)

        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(initial_text)
        self.text_edit.setMinimumHeight(80)
        self.text_edit.setMaximumHeight(200)
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
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.btn_cancel)

        layout.addLayout(btn_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(container)

        self.adjustSize()

    def _on_save(self):
        text = self.text_edit.toPlainText().strip()
        self.save_requested.emit(self.annotation_id, text)
        self.hide()
        self.closed.emit()

    def _on_delete(self):
        self.delete_requested.emit(self.annotation_id)
        self.hide()
        self.closed.emit()

    def _on_cancel(self):
        self.hide()
        self.closed.emit()

    def show_at(self, global_pos: QPoint):
        """Show popup at a fixed position near the target."""
        self.move(global_pos)
        self.show()
        self.raise_()
        self.text_edit.setFocus()


class AnnotationViewPopup(QFrame):
    """Read-only annotation tooltip that follows the cursor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.setMaximumWidth(320)

        container = QFrame(self)
        colors = get_theme_colors()
        bg = colors.get("popup_bg", "#333333")
        text_c = colors.get("text", "#eeeeee")
        border = colors.get("border", "#555555")

        container.setStyleSheet(
            f"QFrame {{ background: {bg}; border: 1px solid {border}; border-radius: 6px; }}"
        )

        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setStyleSheet(
            f"color: {text_c}; padding: 8px 12px; font-size: 12px; border: none; background: transparent;"
        )
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(container)

    def set_text(self, text: str):
        """Set the annotation text to display."""
        display = text if text else "(No note)"
        self.label.setText(display)
        self.adjustSize()

    def show_at_cursor(self, global_pos: QPoint):
        """Show tooltip at cursor position with fixed offset (bottom-right)."""
        offset = QPoint(16, 16)
        self.move(global_pos + offset)
        self.show()
        self.raise_()

    def hide_tooltip(self):
        """Hide the tooltip."""
        self.hide()
