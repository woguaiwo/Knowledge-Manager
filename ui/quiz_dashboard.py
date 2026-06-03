"""
QuizDashboardWidget: grid of topic tiles for Current Focus.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QGridLayout, QFrame, QComboBox
)
from core import database
from core.theme_colors import get_theme_colors
from core.logger import get_logger

_logger = get_logger()

# Proficiency colors per theme
class TopicTile(QFrame):
    clicked = Signal(int, str)  # topic_id, name

    def __init__(self, topic_id: int, name: str, stats: dict, parent=None):
        super().__init__(parent)
        self.topic_id = topic_id
        self.topic_name = name
        self.stats = stats
        self.setFixedSize(180, 120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._apply_color()
        self._setup_ui()

    def _apply_color(self):
        score = self.stats.get("best_score", -1)
        colors = get_theme_colors()
        if score < 0:
            bg = colors["tile_none"]
        elif score >= 80:
            bg = colors["tile_good"]
        elif score >= 50:
            bg = colors["tile_mid"]
        else:
            bg = colors["tile_bad"]
        text = colors["tile_text"]
        self.setStyleSheet(
            f"TopicTile {{ background: {bg}; border-radius: 10px; border: 1px solid {colors['border']}; }}"
            f"TopicTile:hover {{ border: 2px solid {text}; }}"
            f"QLabel {{ color: {text}; }}"
        )

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        lbl_name = QLabel(f"<b>{self.topic_name}</b>")
        lbl_name.setWordWrap(True)
        lbl_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_name)

        qcount = self.stats.get("question_count", 0)
        lbl_info = QLabel(f"{qcount} questions")
        lbl_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_info)

        best = self.stats.get("best_score", -1)
        if best >= 0:
            lbl_score = QLabel(f"Best: {best}%")
            lbl_score.setAlignment(Qt.AlignmentFlag.AlignCenter)
            font = lbl_score.font()
            font.setBold(True)
            font.setPointSize(11)
            lbl_score.setFont(font)
            layout.addWidget(lbl_score)
        else:
            lbl = QLabel("<i>Not attempted</i>")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)

        layout.addStretch()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.topic_id, self.topic_name)
        super().mousePressEvent(event)


class QuizDashboardWidget(QWidget):
    topic_clicked = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tiles_per_row = 4
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(10)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("<b>⭐ Current Focus</b>"))
        toolbar.addStretch()

        self.combo_grid = QComboBox(self)
        self.combo_grid.addItems(["3", "4", "5"])
        self.combo_grid.setCurrentIndex(1)  # default 4
        self.combo_grid.setFixedWidth(50)
        self.combo_grid.currentTextChanged.connect(lambda t: self._set_grid(int(t)))
        toolbar.addWidget(QLabel("Grid:"))
        toolbar.addWidget(self.combo_grid)

        btn_refresh = QPushButton("🔄 Refresh")
        btn_refresh.clicked.connect(self.refresh)
        toolbar.addWidget(btn_refresh)
        main.addLayout(toolbar)

        # Grid area
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(16)
        self.scroll.setWidget(self.grid_container)
        main.addWidget(self.scroll, 1)

    def _set_grid(self, n: int):
        self._tiles_per_row = n
        self.combo_grid.setCurrentText(str(n))
        self.refresh()

    def refresh(self):
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        topics = self._get_focus_topics()
        if not topics:
            lbl = QLabel("<i>No topics in Current Focus.<br>"
                         "Topics with quiz attempts will appear here automatically.<br>"
                         "You can also pin topics via right-click in the sidebar.</i>")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid_layout.addWidget(lbl, 0, 0)
            return

        row, col = 0, 0
        for t in topics:
            stats = self._calc_topic_stats(t["id"])
            tile = TopicTile(t["id"], t["name"], stats)
            tile.clicked.connect(self.topic_clicked.emit)
            self.grid_layout.addWidget(tile, row, col)
            col += 1
            if col >= self._tiles_per_row:
                col = 0
                row += 1

        self.grid_layout.setRowStretch(row + 1, 1)
        self.grid_layout.setColumnStretch(self._tiles_per_row, 1)

    def _get_focus_topics(self) -> list:
        focus = database.get_focus_topics()
        if focus:
            return focus
        all_topics = database.get_all_quiz_topics()
        result = []
        for t in all_topics:
            batches = database.get_quiz_batches_by_topic(t["id"])
            if batches:
                has_attempts = any(
                    database.get_quiz_attempts_by_batch(b["id"])
                    for b in batches
                )
                if has_attempts:
                    result.append(t)
        return result

    def _calc_topic_stats(self, topic_id: int) -> dict:
        batches = database.get_quiz_batches_by_topic(topic_id)
        total_q = sum(b.get("question_count", 0) for b in batches)
        best_score = -1
        for b in batches:
            attempts = database.get_quiz_attempts_by_batch(b["id"])
            if attempts:
                best_score = max(best_score, max(a["score"] for a in attempts))
        return {"question_count": total_q, "best_score": best_score}
