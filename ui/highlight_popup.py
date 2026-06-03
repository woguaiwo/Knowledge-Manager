"""
Mini color-picker popup for text highlighting.
Shows a grid of preset color swatches; emits color_selected when clicked.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QGridLayout, QFrame, QSizePolicy

from core.theme_colors import get_theme_colors


_PRESET_COLORS = [
    "#FFEB3B",  # Yellow
    "#69F0AE",  # Green
    "#40C4FF",  # Blue
    "#FF80AB",  # Pink
    "#FFD180",  # Orange
    "#EA80FC",  # Purple
]


class _ColorSwatch(QFrame):
    """Single clickable color square."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.color = color
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QFrame {{ background: {color}; border-radius: 4px; border: 2px solid #888888; }}"
            f"QFrame:hover {{ border: 2px solid #ffffff; }}"
        )
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            popup = self._get_popup()
            if popup:
                popup._on_color_chosen(self.color)
        event.accept()

    def _get_popup(self):
        parent = self.parent()
        while parent:
            if isinstance(parent, HighlightPopup):
                return parent
            parent = parent.parent()
        return None


class HighlightPopup(QWidget):
    """Floating popup with preset color swatches for highlighting text."""

    color_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        colors = get_theme_colors()
        bg = colors.get("bg", "#2b2b2b")
        text = colors.get("text", "#eeeeee")
        border = colors.get("border", "#555555")
        self.setStyleSheet(
            f"background: {bg}; color: {text}; border-radius: 6px; padding: 4px; border: 1px solid {border};"
        )

        layout = QGridLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        for i, color in enumerate(_PRESET_COLORS):
            swatch = _ColorSwatch(color, self)
            layout.addWidget(swatch, i // 3, i % 3)

        self.adjustSize()

    def _on_color_chosen(self, color: str):
        self.color_selected.emit(color)
        self.close()

    def show_at(self, global_pos):
        """Show popup at the given global position, ensuring it stays on screen."""
        self.adjustSize()
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().availableGeometry()
        x = global_pos.x() - self.width() // 2
        y = global_pos.y() - self.height() - 8
        # Clamp to screen bounds
        x = max(screen.left(), min(x, screen.right() - self.width()))
        y = max(screen.top(), min(y, screen.bottom() - self.height()))
        self.move(x, y)
        self.show()
        self.raise_()
