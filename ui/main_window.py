"""
Main application window for Knowledge Manager.
VSCode-style layout: Activity Bar + Sidebar + Tabbed Main Area + Right Vocab Panel.
"""
import os
from PySide6.QtCore import Qt, QThread, Signal as QSignal, QTimer
from PySide6.QtGui import QAction, QKeySequence, QIcon
from PySide6.QtWidgets import (
    QMainWindow, QFileDialog, QToolBar, QLabel, QDockWidget,
    QMessageBox, QApplication, QDialog, QWidget, QHBoxLayout,
    QTabWidget, QSizePolicy, QSplitter, QFrame, QStackedWidget
)

from core.pdf_engine import PdfEngine
from core import database, api_client
from core.utils import clean_vocab_text, encode_qimage_to_base64
from core.logger import get_logger
logger = get_logger()
from ui.pdf_tab_widget import PdfTabWidget
from ui.pdf_scroll_view import PdfScrollView
from ui.vocab_panel import VocabPanel
from ui.settings_dialog import SettingsDialog
from ui.theme_manager import apply_theme
from core.theme_colors import get_theme_colors
from ui.activity_bar import ActivityBar
from ui.sidebar import Sidebar
from ui.vocab_edit_dialog import VocabEditDialog
from ui.explain_popup import ExplainPopup
from ui.note_panel import NotePanel
from ui.ai_chat_panel import AiChatPanel
from ui.quiz_sidebar import QuizSidebar
from ui.quiz_tab_widget import QuizTabWidget


class GenerationWorker(QThread):
    """Background worker for AI definition generation."""
    result_ready = QSignal(str)

    def __init__(self, words_data, provider):
        super().__init__()
        self.words_data = words_data
        self.provider = provider

    def run(self):
        result = api_client.generate_definitions(
            self.words_data,
            self.provider["base_url"],
            self.provider["api_key"],
            self.provider["model"],
            self.provider.get("proxy", ""),
            float(self.provider.get("temperature", 0.7)),
            int(self.provider.get("max_tokens", 4096)),
        )
        self.result_ready.emit(result)


class ExplainQueryWorker(QThread):
    """Background worker to send a single query."""
    chunk_ready = QSignal(str)
    result_ready = QSignal(str)

    def __init__(self, messages: list, provider: dict, timer_data: dict | None = None):
        super().__init__()
        self.messages = messages
        self.provider = provider
        self.streaming = bool(provider.get("streaming", True))
        self.timer_data = timer_data or {}
        self._first_chunk_emitted = False
        self.cancelled = False

    def run(self):
        import time
        self.timer_data["worker_start"] = time.perf_counter()
        full_text = ""
        try:
            if self.streaming:
                for chunk in api_client.explain_chat_stream(
                    self.messages,
                    self.provider["base_url"],
                    self.provider["api_key"],
                    self.provider["model"],
                    self.provider.get("proxy", ""),
                    float(self.provider.get("temperature", 0.7)),
                    int(self.provider.get("max_tokens", 4096)),
                ):
                    if not self._first_chunk_emitted:
                        self.timer_data["first_chunk"] = time.perf_counter()
                        self._first_chunk_emitted = True
                    if chunk.startswith("Error:"):
                        self.result_ready.emit(chunk)
                        return
                    full_text += chunk
                    self.chunk_ready.emit(chunk)
                self.timer_data["result_ready"] = time.perf_counter()
                self.result_ready.emit(full_text)
            else:
                result = api_client.explain_chat(
                    self.messages,
                    self.provider["base_url"],
                    self.provider["api_key"],
                    self.provider["model"],
                    self.provider.get("proxy", ""),
                    float(self.provider.get("temperature", 0.7)),
                    int(self.provider.get("max_tokens", 4096)),
                )
                self.timer_data["first_chunk"] = time.perf_counter()
                self.timer_data["result_ready"] = time.perf_counter()
                if result.startswith("Error:"):
                    self.result_ready.emit(result)
                    return
                self.chunk_ready.emit(result)
                self.result_ready.emit(result)
        except Exception as e:
            self.result_ready.emit(f"Error: {str(e)}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Knowledge Manager")
        self.setWindowIcon(QIcon("D:/Softwares/Knowledge-Manager/icon.ico"))
        self.setWindowState(Qt.WindowState.WindowMaximized)

        self.zoom = 1.5
        self._gen_worker = None
        self._undo_stack: list[dict] = []
        self._explain_popup = None

        self._setup_ui()
        self._setup_toolbar()
        self._apply_theme()

    # ------------------------------------------------------------------ #
    #  UI Setup
    # ------------------------------------------------------------------ #
    def _setup_ui(self):
        # Central layout: ActivityBar | Splitter(left_panel + tab_widget)
        central = QWidget()
        hlayout = QHBoxLayout(central)
        hlayout.setContentsMargins(0, 0, 0, 0)
        hlayout.setSpacing(0)

        # Left Activity Bar
        self.activity_bar = ActivityBar(central)
        self.activity_bar.explorer_clicked.connect(self._toggle_explorer)
        self.activity_bar.mask_toggled.connect(self._toggle_mask_mode)
        self.activity_bar.vocab_toggled.connect(self._toggle_vocab_mode)
        self.activity_bar.explain_toggled.connect(self._toggle_explain_mode)
        self.activity_bar.vocab_context_menu_requested.connect(self.open_vocab_edit_dialog)
        self.activity_bar.show_vocab_panel_requested.connect(self._show_vocab_panel)
        self.activity_bar.note_toggled.connect(self._toggle_note_mode)
        self.activity_bar.ai_toggled.connect(self._toggle_ai_mode)
        self.activity_bar.quiz_toggled.connect(self._toggle_quiz_mode)
        hlayout.addWidget(self.activity_bar)

        # Vertical divider between ActivityBar and left panel
        self.left_divider = QFrame(central)
        self.left_divider.setFrameShape(QFrame.Shape.VLine)
        self.left_divider.setFixedWidth(1)
        hlayout.addWidget(self.left_divider)

        # Left panel container (holds Sidebar, AI Chat, or Quiz Sidebar)
        left_panel = QWidget(central)
        left_layout = QHBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self.sidebar = Sidebar(left_panel)
        self.sidebar.file_selected.connect(self._open_pdf_in_new_tab)
        self.sidebar.open_folder_requested.connect(self._open_folder)
        self.sidebar.hide()
        left_layout.addWidget(self.sidebar)

        # Vertical divider between sidebar and quiz/ai area (theme-adaptive)
        self._left_divider = QFrame(left_panel)
        self._left_divider.setFrameShape(QFrame.Shape.VLine)
        self._left_divider.setFixedWidth(1)
        self._left_divider.hide()
        left_layout.addWidget(self._left_divider)

        # Quiz sidebar on the LEFT of AI chat
        self.quiz_sidebar = QuizSidebar(left_panel)
        self.quiz_sidebar.hide()
        left_layout.addWidget(self.quiz_sidebar)

        # Vertical divider between quiz and ai (theme-adaptive)
        self._quiz_ai_divider = QFrame(left_panel)
        self._quiz_ai_divider.setFrameShape(QFrame.Shape.VLine)
        self._quiz_ai_divider.setFixedWidth(1)
        self._quiz_ai_divider.hide()
        left_layout.addWidget(self._quiz_ai_divider)

        # AI chat panel on the RIGHT of quiz
        self.ai_chat_panel = AiChatPanel(left_panel)
        self.ai_chat_panel.hide()
        left_layout.addWidget(self.ai_chat_panel)

        # Right area: QStackedWidget switches between PDF and Quiz
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.tabBar().setExpanding(False)
        self.tab_widget.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.tab_widget.tabBar().setUsesScrollButtons(True)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        self.tab_widget.tabCloseRequested.connect(self._on_tab_close)
        self.tab_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.quiz_tab_widget = QuizTabWidget(central)

        self.main_stack = QStackedWidget(central)
        self.main_stack.addWidget(self.tab_widget)      # index 0: PDF view
        self.main_stack.addWidget(self.quiz_tab_widget) # index 1: Quiz view
        self.main_stack.setCurrentIndex(0)

        # Connect quiz sidebar signals
        self.quiz_sidebar.focus_selected.connect(self._on_quiz_focus_selected)
        self.quiz_sidebar.topic_selected.connect(self.quiz_tab_widget.open_topic_tab)

        # Horizontal splitter: left_panel | main_stack
        self.splitter = QSplitter(Qt.Orientation.Horizontal, central)
        self.splitter.addWidget(left_panel)
        self.splitter.addWidget(self.main_stack)
        self.splitter.setSizes([0, 1600])
        self.splitter.setHandleWidth(1)

        hlayout.addWidget(self.splitter, 1)
        self.setCentralWidget(central)

        # Right dock: Vocabulary Panel
        self.vocab_panel = VocabPanel(self)
        self.vocab_panel.request_generate.connect(self._on_generate_definitions)
        self.vocab_panel.vocab_changed.connect(self._sync_collected_marks)
        self.vocab_panel.vocab_saved.connect(self._on_vocab_saved)
        self.vocab_dock = QDockWidget("Vocabulary", self)
        self.vocab_dock.setWidget(self.vocab_panel)
        self.vocab_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.vocab_dock)
        self.vocab_dock.hide()

        # Right dock: Note Panel
        self.note_panel = NotePanel(self)
        self.note_dock = QDockWidget("Notes", self)
        self.note_dock.setWidget(self.note_panel)
        self.note_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.note_dock)
        self.note_dock.hide()



        # Status bar
        self.status_label = QLabel("Ready")
        self.statusBar().addWidget(self.status_label)

    def _setup_toolbar(self):
        self.toolbar = QToolBar("Main")
        self.addToolBar(self.toolbar)

        self.act_open = QAction("📂 Open PDF", self)
        self.act_open.triggered.connect(self._open_pdf_dialog)
        self.toolbar.addAction(self.act_open)

        self.toolbar.addSeparator()

        self.act_zoom_out = QAction("🔍 -", self)
        self.act_zoom_out.triggered.connect(lambda: self._change_zoom(-0.1))
        self.toolbar.addAction(self.act_zoom_out)

        self.lbl_zoom = QLabel(f"{int(self.zoom * 100)}%")
        self.lbl_zoom.setStyleSheet("padding: 0 6px;")
        self.toolbar.addWidget(self.lbl_zoom)

        self.act_zoom_in = QAction("🔍 +", self)
        self.act_zoom_in.triggered.connect(lambda: self._change_zoom(0.1))
        self.toolbar.addAction(self.act_zoom_in)

        self.toolbar.addSeparator()

        self.act_settings = QAction("⚙️ Settings", self)
        self.act_settings.triggered.connect(self._open_settings)
        self.toolbar.addAction(self.act_settings)

        self.toolbar.addSeparator()

        self.act_highlight = QAction("🖍️ Highlight", self)
        self.act_highlight.setCheckable(True)
        self.act_highlight.triggered.connect(self._toggle_highlight_mode)
        self.toolbar.addAction(self.act_highlight)

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #
    def _current_tab(self) -> PdfTabWidget | None:
        idx = self.tab_widget.currentIndex()
        if idx < 0:
            return None
        widget = self.tab_widget.widget(idx)
        return widget if isinstance(widget, PdfTabWidget) else None

    def _apply_theme(self, theme_name: str = None):
        app = QApplication.instance()
        if app is None:
            return
        if theme_name is None:
            theme_name = database.get_setting("theme", "dark")
        apply_theme(app, theme_name)
        # Sync divider color to current theme
        from ui.theme_manager import THEMES
        colors = THEMES.get(theme_name, THEMES["dark"]).get("popup", {})
        text = colors.get("text", "#eeeeee")
        if hasattr(self, 'left_divider'):
            self.left_divider.setStyleSheet(f"background-color: {text};")
        if self._explain_popup is not None:
            self._explain_popup.apply_theme(theme_name)
        # Refresh quiz widgets for new theme colors
        self._refresh_quiz_theme()
        # Refresh PDF highlight widgets for new theme colors
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if isinstance(tab, PdfTabWidget) and tab.scroll_view:
                for pv in tab.scroll_view.page_views:
                    for hw in pv.highlight_widgets:
                        hw.update()

    # ------------------------------------------------------------------ #
    #  Explorer / Sidebar
    # ------------------------------------------------------------------ #
    def _update_left_dividers(self):
        """Show/hide vertical dividers based on visible panels."""
        colors = get_theme_colors()
        text_color = colors['text']  # white on dark, black on light
        # Sidebar divider: visible when sidebar is shown alongside quiz or ai
        show_sidebar_div = self.sidebar.isVisible() and (
            self.quiz_sidebar.isVisible() or self.ai_chat_panel.isVisible()
        )
        self._left_divider.setVisible(show_sidebar_div)
        self._left_divider.setStyleSheet(f"background: {text_color}; color: {text_color};")

        # Quiz-AI divider: visible when both quiz and ai are shown
        show_quiz_ai_div = self.quiz_sidebar.isVisible() and self.ai_chat_panel.isVisible()
        self._quiz_ai_divider.setVisible(show_quiz_ai_div)
        self._quiz_ai_divider.setStyleSheet(f"background: {text_color}; color: {text_color};")

    def _update_splitter_sizes(self):
        """Collapse left panel when nothing is visible on the left."""
        if self.sidebar.isVisible() or self.ai_chat_panel.isVisible() or self.quiz_sidebar.isVisible():
            # Ensure left panel has reasonable width
            if self.splitter.sizes()[0] < 100:
                total = self.splitter.width()
                self.splitter.setSizes([280, total - 280])
        else:
            # Collapse left panel fully
            total = self.splitter.width()
            self.splitter.setSizes([0, total])

    def _toggle_explorer(self):
        checked = self.activity_bar.btn_explorer.isChecked()
        self.sidebar.setVisible(checked)
        if checked:
            # Mutually exclusive with AI Chat
            self.ai_chat_panel.hide()
            self.activity_bar.set_ai_checked(False)
        self._update_left_dividers()
        self._update_splitter_sizes()

    def _show_vocab_panel(self):
        self.vocab_dock.show()

    def _open_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Open Folder")
        if path:
            self.sidebar.set_root_folder(path)
            self.sidebar.show()
            self.activity_bar.set_explorer_checked(True)
            self._update_splitter_sizes()

    # ------------------------------------------------------------------ #
    #  Tab Management
    # ------------------------------------------------------------------ #
    def _open_pdf_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF Files (*.pdf)")
        if path:
            self._open_pdf_in_new_tab(path)

    def _open_pdf_in_new_tab(self, path: str):
        # Check if already open
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if isinstance(tab, PdfTabWidget) and tab.pdf_path == path:
                self.tab_widget.setCurrentIndex(i)
                return

        tab = PdfTabWidget(path, zoom=self.zoom)
        if tab.scroll_view is None:
            QMessageBox.critical(self, "Error", f"Failed to load PDF:\n{path}")
            return

        # Connect signals
        tab.scroll_view.word_hovered.connect(self._on_word_hovered)
        tab.scroll_view.word_clicked.connect(self._on_word_clicked)
        tab.scroll_view.request_zoom.connect(self._change_zoom)
        tab.scroll_view.words_collected.connect(self._on_words_collected)
        tab.scroll_view.explain_requested.connect(self._on_explain_requested)
        tab.scroll_view.image_clicked.connect(self._on_image_explain_requested)
        tab.scroll_view.page_double_clicked.connect(self._on_page_double_clicked)
        tab.scroll_view.link_clicked.connect(self._on_link_clicked)
        tab.scroll_view.page_changed.connect(self.note_panel.on_page_changed)

        # Auto-load saved vocabulary if a mapped file exists
        loaded_from_file = database.load_vocab_from_file(path)
        if loaded_from_file:
            self.status_label.setText(f"Loaded vocabulary from saved file for {os.path.basename(path)}")

        # Restore collected marks (from DB, either freshly loaded or pre-existing)
        words = database.get_vocabulary(path)
        for entry in words:
            tab.mark_word_collected(entry["word"])

        name = os.path.basename(path)
        idx = self.tab_widget.addTab(tab, name)
        self.tab_widget.setCurrentIndex(idx)
        self.vocab_panel.set_pdf(path)
        self.note_panel.set_pdf(path, tab.engine.page_count if tab.engine else 0)
        if not loaded_from_file:
            self.status_label.setText(f"Opened: {name}")

    def _on_tab_changed(self, index: int):
        if index < 0:
            self.vocab_panel.set_pdf("")
            self.note_panel.set_pdf("")
            self.activity_bar.set_mask_checked(False)
            self.activity_bar.set_vocab_checked(False)
            self.activity_bar.set_explain_checked(False)
            self.activity_bar.set_note_checked(False)
            self.activity_bar.set_explorer_checked(False)
            self.sidebar.hide()
            self._update_splitter_sizes()
            self.lbl_zoom.setText(f"{int(self.zoom * 100)}%")
            if self._explain_popup:
                self._explain_popup.hide()
                self._explain_popup = None
            return
        tab = self.tab_widget.widget(index)
        if not isinstance(tab, PdfTabWidget):
            return
        self.vocab_panel.set_pdf(tab.pdf_path)
        current_page = getattr(tab.scroll_view, '_last_primary_page', 0) if tab.scroll_view else 0
        self.note_panel.set_pdf(tab.pdf_path, tab.engine.page_count if tab.engine else 0, current_page)
        self.activity_bar.set_mask_checked(tab.mask_mode)
        self.activity_bar.set_vocab_checked(tab.vocab_mode)
        self.activity_bar.set_explain_checked(tab.explain_mode)
        self.activity_bar.set_note_checked(tab.note_mode)
        self.lbl_zoom.setText(f"{int(tab.zoom * 100)}%")
        if tab.note_mode:
            self.note_dock.show()
        else:
            self.note_dock.hide()
        if self._explain_popup:
            self._explain_popup.hide()
            self._explain_popup = None

    def _on_tab_close(self, index: int):
        tab = self.tab_widget.widget(index)
        if isinstance(tab, PdfTabWidget):
            tab.close_engine()
        self.tab_widget.removeTab(index)
        if self.tab_widget.count() == 0:
            self._undo_stack.clear()
            self.vocab_panel.set_pdf("")
            self.note_panel.set_pdf("")

    # ------------------------------------------------------------------ #
    #  Zoom
    # ------------------------------------------------------------------ #
    def _change_zoom(self, delta: float):
        tab = self._current_tab()
        if tab is None:
            return
        new_zoom = round(tab.zoom + delta, 1)
        if new_zoom < 0.5:
            new_zoom = 0.5
        if new_zoom > 3.0:
            new_zoom = 3.0
        if new_zoom == tab.zoom:
            return

        # Record scroll ratio before rescale
        scroll_ratio = 0.0
        if tab.scroll_view:
            sb = tab.scroll_view.scroll_area.verticalScrollBar()
            max_scroll = max(1, sb.maximum())
            scroll_ratio = sb.value() / max_scroll

        tab.rescale(new_zoom)
        self.lbl_zoom.setText(f"{int(new_zoom * 100)}%")

        # Restore mask mode after rescale
        if tab.mask_mode:
            try:
                ratio = float(database.get_setting("mask_ratio", "35")) / 100.0
            except ValueError:
                ratio = 0.35
            tab.set_mask_mode(True, ratio)

        # Restore scroll position proportionally after layout settles
        def _restore_scroll():
            if not tab.scroll_view:
                return
            sb = tab.scroll_view.scroll_area.verticalScrollBar()
            max_scroll = max(1, sb.maximum())
            sb.setValue(int(scroll_ratio * max_scroll))
        QTimer.singleShot(50, _restore_scroll)

    # ------------------------------------------------------------------ #
    #  Mode Toggles (per-tab)
    # ------------------------------------------------------------------ #
    def _toggle_mask_mode(self, checked: bool):
        tab = self._current_tab()
        if tab is None:
            QMessageBox.warning(self, "Warning", "Please open a PDF first.")
            self.activity_bar.set_mask_checked(False)
            return
        tab.mask_mode = checked
        try:
            ratio = float(database.get_setting("mask_ratio", "35")) / 100.0
        except ValueError:
            ratio = 0.35
        tab.set_mask_mode(checked, ratio)
        self.status_label.setText(f"Mask Mode: {'ON' if checked else 'OFF'}")

    def _toggle_vocab_mode(self, checked: bool):
        tab = self._current_tab()
        if tab is None:
            QMessageBox.warning(self, "Warning", "Please open a PDF first.")
            self.activity_bar.set_vocab_checked(False)
            return
        tab.vocab_mode = checked
        tab.set_vocab_mode(checked)
        self.status_label.setText(f"Vocab Mode: {'ON' if checked else 'OFF'}")

    def _toggle_explain_mode(self, checked: bool):
        tab = self._current_tab()
        if tab is None:
            QMessageBox.warning(self, "Warning", "Please open a PDF first.")
            self.activity_bar.set_explain_checked(False)
            return
        if checked:
            # Mutually exclusive with vocab mode
            if tab.vocab_mode:
                self._toggle_vocab_mode(False)
                self.activity_bar.set_vocab_checked(False)
            tab.explain_mode = True
            tab.set_explain_mode(True)
            tab.explain_ready = False
            tab.explain_messages = []
            provider = database.get_default_ai_provider()
            if not provider or not provider.get("api_key"):
                QMessageBox.warning(self, "Warning", "No AI provider configured. Please open Settings.")
                self.activity_bar.set_explain_checked(False)
                tab.explain_mode = False
                tab.set_explain_mode(False)
                return
            tab.explain_ready = True
            tab.explain_messages = [
                {"role": "system", "content": "You are a helpful reading assistant. The user is reading a document and will ask you to explain words or phrases. Reply in Chinese with detailed explanations including definition and usage."}
            ]
            self.status_label.setText("Explain Mode: ON")
        else:
            tab.explain_mode = False
            tab.explain_ready = False
            tab.set_explain_mode(False)
            if self._explain_popup:
                self._explain_popup.hide()
                self._explain_popup = None
            if tab._explain_worker is not None:
                tab._explain_worker.cancelled = True
                tab._explain_worker = None
                # Let old worker finish naturally; do NOT terminate() or disconnect()
            self.status_label.setText("Explain Mode: OFF")

    def _toggle_note_mode(self, checked: bool):
        tab = self._current_tab()
        if tab is None:
            QMessageBox.warning(self, "Warning", "Please open a PDF first.")
            self.activity_bar.set_note_checked(False)
            return
        tab.note_mode = checked
        if checked:
            self.note_dock.show()
            current_page = getattr(tab.scroll_view, '_last_primary_page', 0) if tab.scroll_view else 0
            self.note_panel.set_pdf(tab.pdf_path, tab.engine.page_count if tab.engine else 0, current_page)
            self.status_label.setText("Note Mode: ON")
        else:
            self.note_dock.hide()
            self.status_label.setText("Note Mode: OFF")

    def _toggle_ai_mode(self, checked: bool):
        if checked:
            self.ai_chat_panel.show()
            # Mutually exclusive with Explorer
            self.sidebar.hide()
            self.activity_bar.set_explorer_checked(False)
            self.status_label.setText("AI Chat Mode: ON")
        else:
            self.ai_chat_panel.hide()
            self.status_label.setText("AI Chat Mode: OFF")
        self._update_left_dividers()
        self._update_splitter_sizes()

    def _toggle_quiz_mode(self, checked: bool):
        if checked:
            # Hide PDF-related panels
            self.sidebar.hide()
            self.vocab_dock.hide()
            self.note_dock.hide()
            self.activity_bar.set_explorer_checked(False)
            self.activity_bar.set_mask_checked(False)
            self.activity_bar.set_vocab_checked(False)
            self.activity_bar.set_explain_checked(False)
            self.activity_bar.set_note_checked(False)
            # Show Quiz (keep AI chat visible if user wants both)
            self.quiz_sidebar.show()
            self.main_stack.setCurrentIndex(1)
            self.quiz_sidebar.refresh()
            self.quiz_tab_widget.refresh_dashboard()
            self.status_label.setText("Quiz Mode: ON")
        else:
            self.quiz_sidebar.hide()
            self.main_stack.setCurrentIndex(0)
            self.status_label.setText("Quiz Mode: OFF")
        self._update_left_dividers()
        self._update_splitter_sizes()

    def _on_quiz_focus_selected(self):
        self.quiz_tab_widget.setCurrentIndex(0)
        self.quiz_tab_widget.refresh_dashboard()

    def _refresh_quiz_theme(self):
        """Re-apply theme colors to all visible quiz widgets."""
        if hasattr(self, 'quiz_sidebar'):
            self.quiz_sidebar.refresh()
        if hasattr(self, 'quiz_tab_widget'):
            self.quiz_tab_widget.refresh_theme()
        self._update_left_dividers()

    def _on_explain_requested(self, selected_text: str, context: str, global_pos):
        from PySide6.QtCore import QPoint
        tab = self._current_tab()
        if tab is None or not tab.explain_mode or not tab.explain_ready:
            return
        # If a previous worker is still running, force-terminate it so the user
        # can immediately start a new explanation without waiting.
        if tab._explain_worker is not None:
            tab._explain_worker.cancelled = True
            tab._explain_worker = None
            # Let old worker finish naturally; do NOT terminate() or disconnect()
        if self._explain_popup:
            self._explain_popup.hide()
            self._explain_popup = None

        popup = ExplainPopup(current_word=selected_text, parent=self)
        popup.set_thinking(True)
        popup.show_near_cursor()

        # Reset conversation for each new word/phrase, keeping only system prompt
        tab.explain_messages = [
            {"role": "system", "content": "You are a helpful reading assistant. The user is reading a document and will ask you to explain words or phrases. Reply in Chinese with detailed explanations including definition and usage."}
        ]

        user_msg = f'请解释这个词/短语："{selected_text}"'
        if context:
            user_msg += f'\n上下文：{context}'
        user_msg += '\n请用中文详细解释，包括定义和用法。'
        tab.explain_messages.append({"role": "user", "content": user_msg})
        popup.append_text(f'**[Query]** {selected_text}')

        provider = database.get_default_ai_provider()
        if not provider:
            popup.set_text("Error: No AI provider configured.")
            popup.set_thinking(False)
            return

        worker = ExplainQueryWorker(tab.explain_messages.copy(), provider)
        tab._explain_worker = worker

        def on_chunk(chunk):
            if not worker.cancelled:
                popup.append_stream_chunk(chunk)

        def on_result(result):
            if not worker.cancelled:
                self._on_explain_result(result, tab, popup)

        def on_finished():
            if tab._explain_worker is worker:
                tab._explain_worker = None

        worker.chunk_ready.connect(on_chunk)
        worker.result_ready.connect(on_result)
        worker.finished.connect(on_finished)
        worker.start()
        popup.start_stream()

        self._explain_popup = popup
        popup.follow_up_requested.connect(lambda text: self._on_explain_follow_up(text, tab, popup))
        popup.save_requested.connect(lambda word, resp: self._on_explain_save(word, resp, tab))
        popup.closed.connect(self._on_explain_popup_closed)

    def _on_explain_result(self, result: str, tab, popup):
        if tab != self._current_tab():
            return
        popup.finish_stream()
        if result.startswith("Error:"):
            # Detect image-not-supported errors and show a friendly message
            lower_err = result.lower()
            if any(k in lower_err for k in ("image", "vision", "multimodal", "file", "content type")):
                popup.append_text(
                    "\n\n⚠️ **当前 AI 模型不支持图像解析。**\n"
                    "请切换到支持视觉的模型（如 GPT-4o、Claude 3、Gemini 等），\n"
                    "或在 Settings 中更换 Provider。"
                )
            else:
                popup.append_text(f"[Error] {result}")
        else:
            tab.explain_messages.append({"role": "assistant", "content": result})
        popup.set_thinking(False)

    def _cleanup_explain_worker(self, tab):
        # Kept for compatibility; actual cleanup is done in on_finished closure
        pass

    def _on_explain_follow_up(self, text: str, tab, popup):
        if tab._explain_worker is not None:
            return
        tab.explain_messages.append({"role": "user", "content": text})
        provider = database.get_default_ai_provider()
        if not provider:
            popup.append_text("[Error] No AI provider configured.")
            popup.set_thinking(False)
            return
        worker = ExplainQueryWorker(tab.explain_messages.copy(), provider)
        tab._explain_worker = worker

        def on_chunk(chunk):
            if not worker.cancelled:
                popup.append_stream_chunk(chunk)

        def on_result(result):
            if not worker.cancelled:
                self._on_explain_result(result, tab, popup)

        def on_finished():
            if tab._explain_worker is worker:
                tab._explain_worker = None

        worker.chunk_ready.connect(on_chunk)
        worker.result_ready.connect(on_result)
        worker.finished.connect(on_finished)
        worker.start()
        popup.start_stream()

    def _clear_all_image_selections(self, tab):
        """Clear selected state on all ImageHitWidgets in the tab."""
        if tab.scroll_view:
            for pv in tab.scroll_view.page_views:
                for iw in pv.image_hit_widgets:
                    iw.set_selected(False)

    def _on_image_explain_requested(self, page_number: int, image_index: int):
        """User clicked on an image in the PDF."""
        import time
        timer = {"start": time.perf_counter(), "type": f"Image(page={page_number},idx={image_index})"}
        tab = self._current_tab()
        if tab is None or not tab.engine:
            return

        # Find the ImageHitWidget and set it as selected
        self._clear_all_image_selections(tab)
        for pv in tab.scroll_view.page_views if tab.scroll_view else []:
            for iw in pv.image_hit_widgets:
                if iw.page_number == page_number and iw.image_index == image_index:
                    iw.set_selected(True)
                    break

        if not tab.explain_mode or not tab.explain_ready:
            return

        # Extract image bytes from PDF
        img_bytes = tab.engine.extract_image_bytes(page_number, image_index)
        timer["extract_done"] = time.perf_counter()
        if not img_bytes:
            QMessageBox.warning(self, "Error", "Failed to extract image from PDF.")
            return

        import base64
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        mime = "image/jpeg"
        if img_bytes[:8].startswith(b"\x89PNG"):
            mime = "image/png"
        elif img_bytes[:3] == b"GIF":
            mime = "image/gif"
        elif img_bytes[:2] == b"BM":
            mime = "image/bmp"
        timer["encode_done"] = time.perf_counter()

        self._run_explain_with_image(
            tab,
            text_prompt="请解释这张图片的内容和含义",
            image_b64=b64,
            image_mime=mime,
            display_title="[Image]",
            timer_data=timer
        )

    def _on_page_double_clicked(self, page_number: int):
        """User double-clicked on empty page area. Explain the whole page."""
        import time
        timer = {"start": time.perf_counter(), "type": f"Page(page={page_number})"}
        tab = self._current_tab()
        if tab is None or not tab.explain_mode or not tab.explain_ready:
            return
        if not tab.engine or not tab.scroll_view:
            return

        # Use the already-rendered pixmap instead of re-rendering via PyMuPDF
        page_view = None
        for pv in tab.scroll_view.page_views:
            if pv.page_number == page_number:
                page_view = pv
                break
        if page_view is None:
            return

        pixmap = page_view.image_label.pixmap()
        if pixmap is None or pixmap.isNull():
            QMessageBox.warning(self, "Error", "Failed to get page image.")
            return
        timer["snapshot_done"] = time.perf_counter()

        b64, mime = encode_qimage_to_base64(pixmap.toImage(), max_size=1024, quality=75)
        timer["encode_done"] = time.perf_counter()
        if not b64:
            QMessageBox.warning(self, "Error", "Failed to encode page image.")
            return

        self._run_explain_with_image(
            tab,
            text_prompt="请解释这个页面的内容",
            image_b64=b64,
            image_mime=mime,
            display_title="[Page]",
            timer_data=timer
        )

    def _on_link_clicked(self, link_data: dict):
        """Handle PDF link clicks: internal page jumps or external URIs."""
        kind = link_data.get("kind", "")
        if kind == "goto":
            target_page = link_data.get("target_page", -1)
            target_y = int(link_data.get("target_y", 0))
            if target_page >= 0:
                tab = self._current_tab()
                if tab:
                    tab.scroll_to_page(target_page, target_y)
        elif kind == "uri":
            uri = link_data.get("uri", "")
            if uri:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl(uri))

    def _toggle_highlight_mode(self, checked: bool):
        """Toggle text highlight mode for the current PDF tab."""
        tab = self._current_tab()
        if tab:
            tab.set_highlight_mode(checked)
            self.status_label.setText("Highlight Mode: ON" if checked else "Highlight Mode: OFF")

    def _run_explain_with_image(self, tab, text_prompt: str, image_b64: str, image_mime: str, display_title: str, timer_data: dict | None = None):
        """Common logic for image-based explain queries."""
        import time
        timer = timer_data or {}
        label = timer.get("type", display_title)

        def _log_timer():
            pass  # Timer logging disabled

        # Terminate previous worker
        if tab._explain_worker is not None:
            tab._explain_worker.cancelled = True
            tab._explain_worker = None
            # Let old worker finish naturally; do NOT terminate() or disconnect()
        if self._explain_popup:
            self._explain_popup.hide()
            self._explain_popup = None

        popup = ExplainPopup(current_word=display_title, parent=self)
        popup.set_thinking(True)
        popup.show_near_cursor()

        tab.explain_messages = [
            {"role": "system", "content": "You are a helpful reading assistant. The user is reading a document and may ask you to explain images or pages. Reply in Chinese with detailed explanations."}
        ]

        multimodal_content = [
            {"type": "text", "text": text_prompt},
            {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{image_b64}"}}
        ]
        tab.explain_messages.append({"role": "user", "content": multimodal_content})
        popup.append_text(f'**[Query]** {display_title}')

        provider = database.get_default_ai_provider()
        if not provider:
            popup.set_text("Error: No AI provider configured.")
            popup.set_thinking(False)
            return

        timer["before_worker"] = time.perf_counter()
        worker = ExplainQueryWorker(tab.explain_messages.copy(), provider, timer_data=timer)
        tab._explain_worker = worker

        def on_chunk(chunk):
            if not worker.cancelled:
                popup.append_stream_chunk(chunk)

        def on_result(result):
            if not worker.cancelled:
                self._on_explain_result(result, tab, popup)
                _log_timer()

        def on_finished():
            if tab._explain_worker is worker:
                tab._explain_worker = None

        worker.chunk_ready.connect(on_chunk)
        worker.result_ready.connect(on_result)
        worker.finished.connect(on_finished)
        worker.start()
        popup.start_stream()

        self._explain_popup = popup
        popup.follow_up_requested.connect(lambda text: self._on_explain_follow_up(text, tab, popup))
        popup.save_requested.connect(lambda word, resp: self._on_explain_save(word, resp, tab))
        popup.closed.connect(self._on_explain_popup_closed)

    def _on_explain_save(self, word: str, explanation: str, tab):
        database.save_explanation(tab.pdf_path, word, explanation)
        self.status_label.setText(f"Saved explanation for: {word[:40]}{'...' if len(word) > 40 else ''}")

    def _on_explain_popup_closed(self):
        tab = self._current_tab()
        if tab and tab._explain_worker is not None:
            tab._explain_worker.cancelled = True
            tab._explain_worker = None
            # Let old worker finish naturally; do NOT terminate() or disconnect()
        self._explain_popup = None

    # ------------------------------------------------------------------ #
    #  Vocabulary Collection
    # ------------------------------------------------------------------ #
    def _sync_collected_marks(self):
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if isinstance(tab, PdfTabWidget):
                tab.clear_collected_marks()
                words = database.get_vocabulary(tab.pdf_path)
                for entry in words:
                    tab.mark_word_collected(entry["word"])

    def _on_words_collected(self, words: list, page_number: int, context: str = ""):
        tab = self._current_tab()
        if tab is None:
            return
        if not words:
            return
        added_any = False
        entry_ids = []
        added_words = []
        pdf_path = tab.pdf_path

        for word in words:
            cleaned = clean_vocab_text(word)
            if not cleaned or cleaned.isdigit():
                continue

            word_count = len(cleaned.split())
            if word_count == 1:
                entry_type = "word"
            elif word_count <= 5:
                entry_type = "phrase"
            else:
                entry_type = "sentence"

            entry_id = database.add_vocabulary(pdf_path, cleaned, page_number, context, entry_type)
            if entry_id:
                added_any = True
                entry_ids.append(entry_id)
                added_words.append(cleaned)

        if added_any:
            self._undo_stack.append({
                "entry_ids": entry_ids,
                "words": added_words,
                "pdf_path": pdf_path,
            })
            # If this tab is still active, refresh vocab panel
            current = self._current_tab()
            if current and current.pdf_path == pdf_path:
                self.vocab_panel.refresh()
            last_word = added_words[-1]
            wc = len(last_word.split())
            label = "word" if wc == 1 else ("phrase" if wc <= 5 else "sentence")
            self.status_label.setText(
                f"Collected {label}: {last_word[:50]}{'...' if len(last_word) > 50 else ''}"
            )

    def _undo_last_collection(self):
        if not self._undo_stack:
            self.status_label.setText("Nothing to undo.")
            return
        last = self._undo_stack.pop()
        for entry_id in last["entry_ids"]:
            database.remove_vocabulary(entry_id)
        for word in last["words"]:
            for sub_word in word.split():
                for i in range(self.tab_widget.count()):
                    tab = self.tab_widget.widget(i)
                    if isinstance(tab, PdfTabWidget):
                        tab.unmark_word_collected(sub_word)
            for i in range(self.tab_widget.count()):
                tab = self.tab_widget.widget(i)
                if isinstance(tab, PdfTabWidget):
                    tab.unmark_word_collected(word)
        self.vocab_panel.refresh()
        self._sync_collected_marks()
        self.status_label.setText(
            f"Undone: {last['words'][-1][:50]}{'...' if len(last['words'][-1]) > 50 else ''}"
        )

    # ------------------------------------------------------------------ #
    #  Word Events
    # ------------------------------------------------------------------ #
    def _on_word_hovered(self, text: str, page: int, block: int, line: int):
        pass

    def _on_word_clicked(self, text: str, page: int, block: int, line: int):
        pass

    # ------------------------------------------------------------------ #
    #  AI Generation
    # ------------------------------------------------------------------ #
    def _on_generate_definitions(self, provider_id: int):
        if self._gen_worker is not None:
            QMessageBox.information(self, "Info", "AI generation is already in progress. Please wait.")
            return
        tab = self._current_tab()
        if tab is None:
            QMessageBox.information(self, "Info", "No PDF open.")
            return
        words_data = database.get_vocabulary(tab.pdf_path)
        if not words_data:
            QMessageBox.information(self, "Info", "No vocabulary collected yet.")
            return

        provider = database.get_ai_provider(provider_id)
        if not provider:
            QMessageBox.warning(self, "Warning", "Selected AI provider not found.")
            return
        if not provider.get("api_key"):
            QMessageBox.warning(self, "Warning", "API Key not configured for the selected provider.")
            return

        # Pass word + context to the API client
        words_payload = [
            {"word": w["word"], "context": w.get("context", "")}
            for w in words_data
        ]

        self.status_label.setText(f"Generating explanations via {provider['name']}...")
        self._gen_worker = GenerationWorker(words_payload, provider)
        self._gen_worker.result_ready.connect(self._on_generation_finished)
        self._gen_worker.finished.connect(self._on_worker_cleanup)
        self._gen_worker.start()

    def _on_worker_cleanup(self):
        """Safely disconnect signals before releasing worker to prevent use-after-free."""
        if self._gen_worker is not None:
            try:
                self._gen_worker.result_ready.disconnect(self._on_generation_finished)
            except Exception:
                pass
            try:
                self._gen_worker.finished.disconnect(self._on_worker_cleanup)
            except Exception:
                pass
            self._gen_worker = None

    def _on_generation_finished(self, result: str):
        self.vocab_panel.show_generated_result(result)
        self.status_label.setText("Generation complete.")

    def _on_vocab_saved(self, path: str):
        self.status_label.setText(f"Saved vocabulary to {path}")

    def open_vocab_edit_dialog(self):
        tab = self._current_tab()
        if tab is None:
            QMessageBox.information(self, "Info", "No PDF open.")
            return
        dlg = VocabEditDialog(tab.pdf_path, self)
        dlg.entries_changed.connect(self._sync_collected_marks)
        dlg.entries_changed.connect(self.vocab_panel.refresh)
        dlg.exec()

    # ------------------------------------------------------------------ #
    #  Settings
    # ------------------------------------------------------------------ #
    def _open_settings(self):
        old_theme = database.get_setting("theme", "dark")
        dlg = SettingsDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_theme = database.get_setting("theme", "dark")
            if new_theme != old_theme:
                self._apply_theme(new_theme)
            tab = self._current_tab()
            if tab and tab.mask_mode:
                try:
                    ratio = float(database.get_setting("mask_ratio", "35")) / 100.0
                except ValueError:
                    ratio = 0.35
                tab.set_mask_mode(True, ratio)
            # Refresh AI provider list in vocab panel and AI chat panel
            self.vocab_panel._refresh_providers()
            self.ai_chat_panel._refresh_providers()

    # ------------------------------------------------------------------ #
    #  Keyboard Shortcuts
    # ------------------------------------------------------------------ #
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            tab = self._current_tab()
            if tab and tab.scroll_view:
                # Priority: copy selected image if any, else copy selected text, else copy selected highlight
                image = self._get_selected_image(tab)
                if image:
                    QApplication.clipboard().setImage(image)
                    self.status_label.setText("Image copied to clipboard.")
                    event.accept()
                    return
                text = tab.get_all_selected_text()
                if text:
                    QApplication.clipboard().setText(text)
                    self.status_label.setText("Copied to clipboard.")
                    event.accept()
                    return
                hl_text = tab.get_selected_highlight_text()
                if hl_text:
                    QApplication.clipboard().setText(hl_text)
                    self.status_label.setText("Highlight copied to clipboard.")
            event.accept()
            return
        if event.key() == Qt.Key.Key_Z and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._undo_last_collection()
            event.accept()
            return

    def _get_selected_image(self, tab):
        """Return QImage of the currently selected ImageHitWidget, or None."""
        if not tab or not tab.scroll_view or not tab.engine:
            return None
        for pv in tab.scroll_view.page_views:
            for iw in pv.image_hit_widgets:
                if iw.is_selected():
                    img_bytes = tab.engine.extract_image_bytes(iw.page_number, iw.image_index)
                    if img_bytes:
                        from PySide6.QtGui import QImage
                        image = QImage.fromData(img_bytes)
                        if not image.isNull():
                            return image
        return None
        super().keyPressEvent(event)

    def closeEvent(self, event):
        """Backup database on application exit."""
        backup_path = database.backup_database()
        if backup_path:
            self.status_label.setText(f"Database backed up to {backup_path}")
        super().closeEvent(event)
