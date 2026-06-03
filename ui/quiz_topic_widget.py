"""
QuizTopicWidget: browse batches within a topic.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSplitter, QScrollArea, QFrame
)
from core import database
from core.theme_colors import get_theme_colors


class QuizTopicWidget(QWidget):
    batch_opened = Signal(int, str)  # batch_id, title

    def __init__(self, topic_id: int, parent=None):
        super().__init__(parent)
        self.topic_id = topic_id
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # Header
        header = QHBoxLayout()
        header.setContentsMargins(12, 10, 12, 10)
        self.lbl_title = QLabel("<b>Topic</b>")
        self.lbl_title.setStyleSheet("font-size: 16px;")
        header.addWidget(self.lbl_title)
        header.addStretch()
        self.lbl_stats = QLabel("")
        header.addWidget(self.lbl_stats)
        main.addLayout(header)

        # Splitter: batch list (top) | attempts history (bottom)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Top: batch list
        batch_box = QFrame()
        bl = QVBoxLayout(batch_box)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.addWidget(QLabel("<b>📦 Batches</b> — double-click to open"))
        self.batch_list = QListWidget()
        c = get_theme_colors()
        self.batch_list.setStyleSheet(
            f"QListWidget {{ border: none; background: transparent; color: {c['text']}; }}"
            f"QListWidget::item {{ padding: 8px; border-radius: 4px; }}"
            f"QListWidget::item:selected {{ background: {c['selected']}; }}"
        )
        self.batch_list.itemDoubleClicked.connect(self._on_batch_double_clicked)
        bl.addWidget(self.batch_list)
        splitter.addWidget(batch_box)

        # Bottom: attempts history across all batches in this topic
        hist_box = QFrame()
        hl = QVBoxLayout(hist_box)
        hl.setContentsMargins(12, 8, 12, 8)
        hl.addWidget(QLabel("<b>📜 Attempt History</b>"))
        self.history_list = QListWidget()
        self.history_list.setStyleSheet(
            "QListWidget { border: none; background: transparent; }"
            "QListWidget::item { padding: 4px; }"
        )
        hl.addWidget(self.history_list)
        splitter.addWidget(hist_box)
        splitter.setSizes([400, 200])

        main.addWidget(splitter, 1)

    def _load_data(self):
        topic = database.get_quiz_topic(self.topic_id)
        if topic:
            self.lbl_title.setText(f"<b>{topic['name']}</b>")

        batches = database.get_quiz_batches_by_topic(self.topic_id)
        total_q = sum(b.get("question_count", 0) for b in batches)
        self.lbl_stats.setText(f"{len(batches)} batches | {total_q} questions")

        self.batch_list.clear()
        all_attempts = []
        for b in batches:
            best = 0
            attempts = database.get_quiz_attempts_by_batch(b["id"])
            if attempts:
                best = max(a["score"] for a in attempts)
                all_attempts.extend(attempts)
            item = QListWidgetItem(
                f"{b['title']}  ({b['question_count']} Q)  Best: {best}%"
            )
            item.setData(Qt.ItemDataRole.UserRole, b["id"])
            item.setToolTip(f"Created: {b['created_at'][:10]}")
            self.batch_list.addItem(item)

        # History
        self.history_list.clear()
        all_attempts.sort(key=lambda a: a["started_at"], reverse=True)
        for a in all_attempts[:20]:
            batch = database.get_quiz_batch(a["batch_id"])
            btitle = batch["title"] if batch else "Unknown"
            status = "✅" if a["completed_at"] else "⏳"
            item = QListWidgetItem(
                f"{status} {btitle} — {a['score']}% ({a['correct_count']}/{a['total_questions']}) "
                f"@ {a['started_at'][:16]}"
            )
            self.history_list.addItem(item)

    def _on_batch_double_clicked(self, item: QListWidgetItem):
        bid = item.data(Qt.ItemDataRole.UserRole)
        batch = database.get_quiz_batch(bid)
        if batch:
            self.batch_opened.emit(bid, batch["title"])
