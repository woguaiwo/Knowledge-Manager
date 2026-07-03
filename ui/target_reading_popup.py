"""
Floating navigation popup for Target Reading mode.
Shows the current match index, AI explanation, and prev/next controls.
"""
from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLabel, QSizePolicy, QSizeGrip, QApplication
)

from core import database
from ui.theme_manager import THEMES


class TargetReadingPopup(QWidget):
    prev_requested = Signal()
    next_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_pinned = False
        self._dragging = False
        self._drag_start_pos = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMinimumWidth(420)
        self.setMinimumHeight(280)
        self.resize(460, 320)

        self.container = QWidget(self)
        self.container.setObjectName("TargetReadingPopupContainer")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.container)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(10, 10, 10, 10)
        container_layout.setSpacing(8)

        # Header with counter and drag area
        header_layout = QHBoxLayout()
        self.lbl_header = QLabel("🎯 Target Reading")
        self.lbl_header.setStyleSheet("font-weight: bold; font-size: 13px;")
        header_layout.addWidget(self.lbl_header)
        header_layout.addStretch()

        self.lbl_counter = QLabel("0 / 0")
        self.lbl_counter.setStyleSheet("font-weight: bold; font-size: 12px;")
        header_layout.addWidget(self.lbl_counter)
        container_layout.addLayout(header_layout)

        # Explanation display
        self.text_display = QTextEdit()
        self.text_display.setReadOnly(True)
        self.text_display.setPlaceholderText("AI annotation will appear here...")
        self.text_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        container_layout.addWidget(self.text_display)

        # Navigation buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_prev = QPushButton("◀ Prev")
        self.btn_prev.setToolTip("Previous match")
        self.btn_prev.clicked.connect(self.prev_requested.emit)

        self.btn_next = QPushButton("Next ▶")
        self.btn_next.setToolTip("Next match")
        self.btn_next.clicked.connect(self.next_requested.emit)

        self.btn_pin = QPushButton("📌")
        self.btn_pin.setCheckable(True)
        self.btn_pin.setToolTip("Pin (prevent auto-close)")
        self.btn_pin.setFixedWidth(40)
        self.btn_pin.toggled.connect(self._on_pin_toggled)

        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close_requested.emit)

        btn_layout.addWidget(self.btn_prev)
        btn_layout.addWidget(self.btn_next)
        btn_layout.addWidget(self.btn_pin)
        btn_layout.addWidget(self.btn_close)
        btn_layout.addWidget(
            QSizeGrip(self.container),
            alignment=Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight,
        )
        container_layout.addLayout(btn_layout)

        self.apply_theme(database.get_setting("theme", "dark"))

    def set_match(self, index: int, total: int, explanation: str = ""):
        self.lbl_counter.setText(f"{index + 1} / {total}")
        self.text_display.setMarkdown(explanation)
        self.btn_prev.setEnabled(index > 0)
        self.btn_next.setEnabled(index < total - 1)

    # ------------------------------------------------------------------ #
    #  Theme
    # ------------------------------------------------------------------ #
    def apply_theme(self, theme_name: str):
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
            f"#TargetReadingPopupContainer {{"
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
            f"}}"
        )
        self.lbl_header.setStyleSheet(f"color: {header};")

    # ------------------------------------------------------------------ #
    #  Event handling
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
            global_pos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
            if not self.geometry().contains(global_pos):
                self.close_requested.emit()
                return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.pos())
            if child in (None, self, self.container):
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

    def _on_pin_toggled(self, checked: bool):
        self.is_pinned = checked
        if checked:
            self.btn_pin.setText("📍")
            self.btn_pin.setToolTip("Unpin")
        else:
            self.btn_pin.setText("📌")
            self.btn_pin.setToolTip("Pin (prevent auto-close)")
