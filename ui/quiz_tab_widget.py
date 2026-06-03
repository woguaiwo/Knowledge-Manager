"""
QuizTabWidget: manages all quiz-related tabs inside the main window.
Tab 0 = Dashboard (fixed). Tab 1+ = dynamic Topic or Batch tabs.
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTabWidget, QWidget
from ui.quiz_dashboard import QuizDashboardWidget
from ui.quiz_topic_widget import QuizTopicWidget
from ui.quiz_batch import QuizBatchWidget


class QuizTabWidget(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)
        self.tabCloseRequested.connect(self._on_tab_close)

        # Tab 0: Dashboard (fixed)
        self.dashboard = QuizDashboardWidget(self)
        self.dashboard.topic_clicked.connect(self.open_topic_tab)
        self.addTab(self.dashboard, "⭐ Dashboard")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def open_topic_tab(self, topic_id: int, title: str = ""):
        """Open or focus a Topic browse tab."""
        for i in range(1, self.count()):
            w = self.widget(i)
            if isinstance(w, QuizTopicWidget) and w.topic_id == topic_id:
                self.setCurrentIndex(i)
                return
        widget = QuizTopicWidget(topic_id, self)
        widget.batch_opened.connect(self.open_batch_tab)
        tab_title = title or "Topic"
        idx = self.addTab(widget, f"📁 {tab_title}")
        self.setCurrentIndex(idx)

    def open_batch_tab(self, batch_id: int, title: str = ""):
        """Open or focus a Batch quiz tab."""
        for i in range(1, self.count()):
            w = self.widget(i)
            if isinstance(w, QuizBatchWidget) and w.batch_id == batch_id:
                self.setCurrentIndex(i)
                return
        widget = QuizBatchWidget(batch_id, self)
        tab_title = title or "Quiz"
        idx = self.addTab(widget, f"📝 {tab_title}")
        self.setCurrentIndex(idx)

    def refresh_dashboard(self):
        self.dashboard.refresh()

    def refresh_theme(self):
        """Re-apply current theme colors to all quiz widgets."""
        self.dashboard.refresh()
        for i in range(1, self.count()):
            w = self.widget(i)
            if isinstance(w, QuizBatchWidget) and hasattr(w, 'refresh_theme'):
                w.refresh_theme()
            elif isinstance(w, QuizTopicWidget) and hasattr(w, 'refresh_theme'):
                w.refresh_theme()

    # ------------------------------------------------------------------ #
    # Slots
    # ------------------------------------------------------------------ #

    def _on_tab_close(self, index: int):
        if index == 0:
            return  # Dashboard is not closable
        self.removeTab(index)
