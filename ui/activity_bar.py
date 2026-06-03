"""
VSCode-style Activity Bar: narrow vertical strip with icon buttons.
Icons are drawn dynamically via QPainter so no external image files are needed.
"""
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QSizePolicy, QSpacerItem, QMenu


def _create_icon(text: str, bg_color: QColor, size: int = 32) -> QIcon:
    """Draw a simple rounded-square icon with white text."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(bg_color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, size - 4, size - 4, 6, 6)
    painter.setPen(QColor(255, 255, 255))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(14)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return QIcon(pixmap)


class ActivityBar(QWidget):
    """
    Left-side narrow bar with icon buttons for Explorer, Mask Mode, Vocab Mode, Explain Mode.
    """
    explorer_clicked = Signal()
    mask_toggled = Signal(bool)
    vocab_toggled = Signal(bool)
    explain_toggled = Signal(bool)
    note_toggled = Signal(bool)
    ai_toggled = Signal(bool)
    quiz_toggled = Signal(bool)
    vocab_context_menu_requested = Signal()
    show_vocab_panel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(52)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 12, 4, 12)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        # Explorer button
        self.btn_explorer = QPushButton(self)
        self.btn_explorer.setIcon(_create_icon("📁", QColor(80, 80, 80)))
        self.btn_explorer.setIconSize(QSize(32, 32))
        self.btn_explorer.setToolTip("Explorer")
        self.btn_explorer.setCheckable(True)
        self.btn_explorer.setFixedSize(44, 44)
        self.btn_explorer.setStyleSheet(self._btn_style())
        self.btn_explorer.clicked.connect(lambda checked=False: self.explorer_clicked.emit())
        layout.addWidget(self.btn_explorer)

        # Mask Mode button
        self.btn_mask = QPushButton(self)
        self.btn_mask.setIcon(_create_icon("M", QColor(60, 60, 60)))
        self.btn_mask.setIconSize(QSize(32, 32))
        self.btn_mask.setToolTip("Mask Mode")
        self.btn_mask.setCheckable(True)
        self.btn_mask.setFixedSize(44, 44)
        self.btn_mask.setStyleSheet(self._btn_style())
        self.btn_mask.clicked.connect(lambda checked: self.mask_toggled.emit(checked))
        layout.addWidget(self.btn_mask)

        # Vocab Mode button
        self.btn_vocab = QPushButton(self)
        self.btn_vocab.setIcon(_create_icon("V", QColor(60, 120, 80)))
        self.btn_vocab.setIconSize(QSize(32, 32))
        self.btn_vocab.setToolTip("Vocab Mode (right-click for Address Edit)")
        self.btn_vocab.setCheckable(True)
        self.btn_vocab.setFixedSize(44, 44)
        self.btn_vocab.setStyleSheet(self._btn_style())
        self.btn_vocab.clicked.connect(lambda checked: self.vocab_toggled.emit(checked))
        self.btn_vocab.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.btn_vocab.customContextMenuRequested.connect(self._show_vocab_context_menu)
        layout.addWidget(self.btn_vocab)

        # Explain Mode button
        self.btn_explain = QPushButton(self)
        self.btn_explain.setIcon(_create_icon("E", QColor(0, 150, 136)))
        self.btn_explain.setIconSize(QSize(32, 32))
        self.btn_explain.setToolTip("Explain Mode")
        self.btn_explain.setCheckable(True)
        self.btn_explain.setFixedSize(44, 44)
        self.btn_explain.setStyleSheet(self._btn_style())
        self.btn_explain.clicked.connect(lambda checked: self.explain_toggled.emit(checked))
        layout.addWidget(self.btn_explain)

        # Note Mode button
        self.btn_note = QPushButton(self)
        self.btn_note.setIcon(_create_icon("N", QColor(212, 160, 23)))
        self.btn_note.setIconSize(QSize(32, 32))
        self.btn_note.setToolTip("Note Mode")
        self.btn_note.setCheckable(True)
        self.btn_note.setFixedSize(44, 44)
        self.btn_note.setStyleSheet(self._btn_style())
        self.btn_note.clicked.connect(lambda checked: self.note_toggled.emit(checked))
        layout.addWidget(self.btn_note)

        # AI Chat Mode button
        self.btn_ai = QPushButton(self)
        self.btn_ai.setIcon(_create_icon("A", QColor(100, 149, 237)))
        self.btn_ai.setIconSize(QSize(32, 32))
        self.btn_ai.setToolTip("AI Chat Mode")
        self.btn_ai.setCheckable(True)
        self.btn_ai.setFixedSize(44, 44)
        self.btn_ai.setStyleSheet(self._btn_style())
        self.btn_ai.clicked.connect(lambda checked: self.ai_toggled.emit(checked))
        layout.addWidget(self.btn_ai)

        # Quiz Mode button
        self.btn_quiz = QPushButton(self)
        self.btn_quiz.setIcon(_create_icon("Q", QColor(180, 80, 180)))
        self.btn_quiz.setIconSize(QSize(32, 32))
        self.btn_quiz.setToolTip("Quiz Mode")
        self.btn_quiz.setCheckable(True)
        self.btn_quiz.setFixedSize(44, 44)
        self.btn_quiz.setStyleSheet(self._btn_style())
        self.btn_quiz.clicked.connect(lambda checked: self.quiz_toggled.emit(checked))
        layout.addWidget(self.btn_quiz)

        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        self.setLayout(layout)

    def _btn_style(self) -> str:
        return (
            "QPushButton {"
            "  border: none;"
            "  border-radius: 4px;"
            "  background: transparent;"
            "}"
            "QPushButton:hover {"
            "  background: rgba(128, 128, 128, 0.25);"
            "}"
            "QPushButton:checked {"
            "  background: rgba(100, 149, 237, 0.35);"
            "}"
        )

    def set_mask_checked(self, checked: bool):
        self.btn_mask.blockSignals(True)
        self.btn_mask.setChecked(checked)
        self.btn_mask.blockSignals(False)

    def set_vocab_checked(self, checked: bool):
        self.btn_vocab.blockSignals(True)
        self.btn_vocab.setChecked(checked)
        self.btn_vocab.blockSignals(False)

    def set_explorer_checked(self, checked: bool):
        self.btn_explorer.blockSignals(True)
        self.btn_explorer.setChecked(checked)
        self.btn_explorer.blockSignals(False)

    def set_explain_checked(self, checked: bool):
        self.btn_explain.blockSignals(True)
        self.btn_explain.setChecked(checked)
        self.btn_explain.blockSignals(False)

    def set_note_checked(self, checked: bool):
        self.btn_note.blockSignals(True)
        self.btn_note.setChecked(checked)
        self.btn_note.blockSignals(False)

    def set_ai_checked(self, checked: bool):
        self.btn_ai.blockSignals(True)
        self.btn_ai.setChecked(checked)
        self.btn_ai.blockSignals(False)

    def set_quiz_checked(self, checked: bool):
        self.btn_quiz.blockSignals(True)
        self.btn_quiz.setChecked(checked)
        self.btn_quiz.blockSignals(False)

    def _show_vocab_context_menu(self, pos):
        menu = QMenu(self)
        action_show = menu.addAction("📚 Show Vocabulary Panel")
        action_show.triggered.connect(self.show_vocab_panel_requested.emit)
        menu.addSeparator()
        action_edit = menu.addAction("📝 Address Edit")
        action_edit.triggered.connect(self.vocab_context_menu_requested.emit)
        menu.exec(self.btn_vocab.mapToGlobal(pos))
