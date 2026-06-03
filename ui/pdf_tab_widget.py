"""
Per-tab widget containing a PdfEngine, PdfScrollView, and tab-specific state.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from core.pdf_engine import PdfEngine
from ui.pdf_scroll_view import PdfScrollView


class PdfTabWidget(QWidget):
    """
    Wrapper for a single open PDF document within a QTabWidget tab.
    Holds its own PdfEngine, zoom level, and mode states.
    """
    def __init__(self, pdf_path: str, zoom: float = 1.5, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.zoom = zoom
        self.mask_mode = False
        self.vocab_mode = False
        self.explain_mode = False
        self.note_mode = False
        self.explain_messages: list[dict] = []
        self.explain_ready = False
        self._explain_worker = None
        self._explain_init_worker = None

        self.engine = PdfEngine()
        loaded = self.engine.load(pdf_path)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if not loaded or self.engine.page_count == 0:
            self.scroll_view = None
            self.placeholder = QLabel("Failed to load PDF.")
            self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.placeholder)
        else:
            self.scroll_view = PdfScrollView(self)
            self.scroll_view.load_document(self.engine, zoom=self.zoom)
            layout.addWidget(self.scroll_view)

        self.setLayout(layout)

    def rescale(self, new_zoom: float):
        if self.scroll_view and self.engine:
            self.zoom = new_zoom
            self.scroll_view.rescale(new_zoom)

    def set_mask_mode(self, active: bool, ratio: float = 0.35):
        self.mask_mode = active
        if self.scroll_view:
            self.scroll_view.set_mask_mode(active, ratio)

    def set_vocab_mode(self, active: bool):
        self.vocab_mode = active
        if self.scroll_view:
            self.scroll_view.set_vocab_mode(active)

    def set_explain_mode(self, active: bool):
        self.explain_mode = active
        if self.scroll_view:
            self.scroll_view.set_explain_mode(active)

    def mark_word_collected(self, text: str):
        if self.scroll_view:
            self.scroll_view.mark_word_collected(text)

    def unmark_word_collected(self, text: str):
        if self.scroll_view:
            self.scroll_view.unmark_word_collected(text)

    def clear_collected_marks(self):
        if self.scroll_view:
            self.scroll_view.clear_collected_marks()

    def clear_all_selections(self):
        if self.scroll_view:
            self.scroll_view.clear_all_selections()

    def get_all_selected_text(self) -> str:
        if self.scroll_view:
            return self.scroll_view.get_all_selected_text()
        return ""

    def get_selected_highlight_text(self) -> str:
        if self.scroll_view:
            return self.scroll_view.get_selected_highlight_text()
        return ""

    def set_highlight_mode(self, active: bool):
        if self.scroll_view:
            self.scroll_view.set_highlight_mode(active)

    def scroll_to_page(self, page_number: int, y_offset: int = 0):
        if self.scroll_view:
            self.scroll_view.scroll_to_page(page_number, y_offset)

    def close_engine(self):
        if self.engine:
            self.engine.close()
            self.engine = None
