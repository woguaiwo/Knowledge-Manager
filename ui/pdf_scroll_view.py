"""
Scrollable view that hosts multiple PageView widgets for a PDF document.
"""
from PySide6.QtCore import Qt, Signal, QEvent, QTimer, QPoint
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QSizePolicy, QLabel

from core.pdf_engine import PdfEngine
from ui.widgets import PageView


class PdfScrollView(QWidget):
    word_hovered = Signal(str, int, int, int)
    word_clicked = Signal(str, int, int, int)
    words_collected = Signal(list, int, str)  # list[str], page_number, context
    explain_requested = Signal(str, str, object)  # selected_text, context, global_pos (QPoint)
    image_clicked = Signal(int, int)  # page_number, image_index
    image_region_selected = Signal(int, object, object)  # page_number, QImage, global_pos
    page_double_clicked = Signal(int)  # page_number
    link_clicked = Signal(dict)  # link data dict
    page_changed = Signal(int)      # 0-based primary visible page index
    request_zoom = Signal(float)    # delta for zoom change

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine: PdfEngine | None = None
        self.page_views: list[PageView] = []
        self.zoom = 1.5
        self._annotation_drag = None
        self._pending_zoom_delta = 0.0
        self._zoom_timer = QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.timeout.connect(self._commit_zoom)

        # Page indicator bar
        self.page_indicator = QLabel("Page 1 / 1")
        self.page_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_indicator.setStyleSheet(
            "QLabel { background: rgba(60, 60, 60, 200); color: #ffffff; "
            "padding: 4px 12px; font-size: 12px; border-bottom: 1px solid #444; }"
        )
        self.page_indicator.setFixedHeight(28)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; }")
        self.scroll_area.viewport().installEventFilter(self)

        self.container = QWidget()
        self.container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.container_layout.setSpacing(20)
        self.container_layout.setContentsMargins(20, 20, 20, 20)

        self.scroll_area.setWidget(self.container)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.page_indicator)
        layout.addWidget(self.scroll_area)
        self.setLayout(layout)

        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.page_changed.connect(self._update_page_indicator)

    def load_document(self, engine: PdfEngine, zoom: float = 1.5):
        self.clear()
        self.engine = engine
        self.zoom = zoom
        if not engine or engine.page_count == 0:
            return
        for i in range(engine.page_count):
            pv = PageView(engine, i, zoom, self.container)
            pv.word_hovered.connect(self.word_hovered)
            pv.word_clicked.connect(self.word_clicked)
            pv.words_collected.connect(self.words_collected)
            pv.explain_requested.connect(self.explain_requested)
            pv.image_clicked.connect(self.image_clicked)
            pv.image_region_selected.connect(self.image_region_selected)
            pv.page_double_clicked.connect(self.page_double_clicked)
            pv.link_clicked.connect(self.link_clicked)
            pv.annotation_drag_started.connect(self._begin_annotation_drag)
            pv.annotation_drag_moved.connect(self._move_annotation_drag)
            pv.annotation_drag_finished.connect(self._finish_annotation_drag)
            self.container_layout.addWidget(pv)
            self.page_views.append(pv)

    def clear(self):
        if self._annotation_drag is not None:
            self._cancel_annotation_drag()
        for pv in self.page_views:
            # Remove any Explain Mode application filter before the page is
            # scheduled for deletion; otherwise a closing tab could continue
            # seeing global mouse events until Qt processes deleteLater().
            pv.set_explain_mode(False)
            self.container_layout.removeWidget(pv)
            pv.deleteLater()
        self.page_views.clear()
        self.engine = None

    def _page_for_annotation_widget(self, widget):
        for pv in self.page_views:
            if widget in pv.annotation_widgets:
                return pv
        return None

    def _page_at_global(self, global_pos):
        for pv in self.page_views:
            if pv.rect().contains(pv.mapFromGlobal(global_pos)):
                return pv
        return None

    @staticmethod
    def _set_annotation_parent(widget, parent):
        """Reparent a dragged icon while preserving its global position."""
        global_top_left = widget.mapToGlobal(QPoint(0, 0))
        hover_label = getattr(widget, "_hover_label", None)
        if hover_label is not None:
            hover_label.hide()
            hover_label.setParent(parent)
        widget.setParent(parent)
        widget.move(parent.mapFromGlobal(global_top_left))
        widget.show()
        widget.raise_()

    def _begin_annotation_drag(self, widget, global_pos):
        if self._annotation_drag is not None:
            return
        source_page = self._page_for_annotation_widget(widget)
        if source_page is None:
            return

        self._annotation_drag = {
            "widget": widget,
            "source_page": source_page,
            "drop_page": source_page,
            "offset": getattr(widget, "_drag_offset", None) or widget.mapFromGlobal(global_pos),
        }
        # The container spans all PDF pages, so the icon remains visible while
        # the pointer crosses a page boundary.
        self._set_annotation_parent(widget, self.container)
        widget.grabMouse()
        self._move_annotation_drag(widget, global_pos)

    def _move_annotation_drag(self, widget, global_pos):
        state = self._annotation_drag
        if state is None or state["widget"] is not widget:
            return
        if widget.parentWidget() is not self.container:
            self._set_annotation_parent(widget, self.container)

        offset = state["offset"]
        top_left = global_pos - offset
        widget.move(self.container.mapFromGlobal(top_left))
        widget.raise_()

        target_page = self._page_at_global(global_pos)
        if target_page is not None:
            state["drop_page"] = target_page

    def _finish_annotation_drag(self, widget, global_pos):
        state = self._annotation_drag
        if state is None or state["widget"] is not widget:
            return
        self._move_annotation_drag(widget, global_pos)

        target_page = self._page_at_global(global_pos) or state["drop_page"] or state["source_page"]
        offset = state["offset"]
        top_left = global_pos - offset
        target_pos = target_page.overlay.mapFromGlobal(top_left)
        max_x = max(0, target_page.overlay.width() - widget.width())
        max_y = max(0, target_page.overlay.height() - widget.height())
        target_x = max(0, min(target_pos.x(), max_x))
        target_y = max(0, min(target_pos.y(), max_y))

        self._set_annotation_parent(widget, target_page.overlay)
        widget.move(target_x, target_y)
        widget.raise_()

        for pv in self.page_views:
            if widget in pv.annotation_widgets:
                pv.annotation_widgets.remove(widget)
        if widget not in target_page.annotation_widgets:
            target_page.annotation_widgets.append(widget)

        new_pdf_x = target_x / target_page.zoom
        new_pdf_y = target_y / target_page.zoom
        widget.unzoomed_pos = (new_pdf_x, new_pdf_y)
        from core import database
        database.update_annotation_position(
            widget.annotation_id,
            new_pdf_x,
            new_pdf_y,
            page_number=target_page.page_number,
        )
        try:
            widget.releaseMouse()
        except Exception:
            pass
        self._annotation_drag = None

    def _cancel_annotation_drag(self):
        state = self._annotation_drag
        if state is None:
            return
        widget = state["widget"]
        source_page = state["source_page"]
        if widget.parentWidget() is self.container:
            self._set_annotation_parent(widget, source_page.overlay)
        try:
            widget.releaseMouse()
        except Exception:
            pass
        self._annotation_drag = None

    def rescale(self, new_zoom: float):
        if not self.engine or new_zoom == self.zoom:
            return
        self.zoom = new_zoom
        for pv in self.page_views:
            pv.rescale(new_zoom, render_image=True)

    def _visible_indices(self) -> set[int]:
        if not self.page_views:
            return set()
        viewport_top = self.scroll_area.verticalScrollBar().value()
        viewport_bottom = viewport_top + self.scroll_area.viewport().height()
        result = set()
        for i, pv in enumerate(self.page_views):
            geo = pv.geometry()
            pv_top = geo.y()
            pv_bottom = pv_top + geo.height()
            if pv_bottom >= viewport_top and pv_top <= viewport_bottom:
                result.add(i)
        return result

    def _primary_visible_page(self) -> int:
        """Return the page with the largest visible area in the viewport."""
        if not self.page_views:
            return -1
        viewport_top = self.scroll_area.verticalScrollBar().value()
        viewport_bottom = viewport_top + self.scroll_area.viewport().height()
        best_page = -1
        best_area = 0
        for i, pv in enumerate(self.page_views):
            geo = pv.geometry()
            pv_top = geo.y()
            pv_bottom = pv_top + geo.height()
            overlap_top = max(pv_top, viewport_top)
            overlap_bottom = min(pv_bottom, viewport_bottom)
            area = max(0, overlap_bottom - overlap_top)
            if area > best_area:
                best_area = area
                best_page = i
        return best_page

    def _on_scroll(self, value):
        for i in self._visible_indices():
            pv = self.page_views[i]
            if getattr(pv, '_image_dirty', False):
                pv._render_image()
        primary = self._primary_visible_page()
        if primary >= 0 and getattr(self, '_last_primary_page', -1) != primary:
            self._last_primary_page = primary
            self.page_changed.emit(primary)

    def _update_page_indicator(self, page_index: int):
        """Update the page indicator label."""
        if self.engine:
            total = self.engine.page_count
            self.page_indicator.setText(f"Page {page_index + 1} / {total}")

    def set_mask_mode(self, active: bool, ratio: float = 0.35):
        for pv in self.page_views:
            pv.apply_mask_mode(active, ratio)

    def set_vocab_mode(self, active: bool):
        for pv in self.page_views:
            pv.vocab_mode = active

    def set_explain_mode(self, active: bool):
        for pv in self.page_views:
            pv.set_explain_mode(active)
            # Make highlights transparent to mouse events in explain mode
            # so users can select text underneath
            for hw in pv.highlight_widgets:
                hw.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, active)
            for iw in pv.image_hit_widgets:
                # Some PDFs contain a full-page image plus an extracted text
                # layer.  Let text selection reach WordWidgets in Explain
                # Mode; PageView's overlay still handles clicks on image-only
                # areas and emits the normal image explanation signal.
                iw.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, active)
            for aw in pv.annotation_widgets:
                # Annotation icons remain independent interactive targets in
                # Explain Mode: hover, pinning, dragging, and double-click
                # editing must continue to work. They simply do not contribute
                # words to an Explain selection because they consume the event.
                aw.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

    def set_annotation_mode(self, active: bool):
        for pv in self.page_views:
            pv.set_annotation_mode(active)

    def mark_word_collected(self, text: str):
        for pv in self.page_views:
            pv.mark_word_collected(text)

    def unmark_word_collected(self, text: str):
        for pv in self.page_views:
            pv.unmark_word_collected(text)

    def clear_collected_marks(self):
        for pv in self.page_views:
            pv.clear_collected_marks()

    def clear_all_selections(self):
        for pv in self.page_views:
            pv.clear_selection()

    def get_all_selected_text(self) -> str:
        parts = []
        for pv in self.page_views:
            if pv.selected_widgets:
                parts.append(pv.get_selected_text())
        return " ".join(parts)

    def get_selected_highlight_text(self) -> str:
        """Return text of the currently selected highlight widget, if any."""
        for pv in self.page_views:
            if pv._selected_highlight:
                return pv._selected_highlight.text
        return ""

    def scroll_to_page(self, page_number: int, y_offset: int = 0):
        """Scroll the view so the given page is visible."""
        if page_number < 0 or page_number >= len(self.page_views):
            return
        pv = self.page_views[page_number]
        target_y = pv.geometry().y() + y_offset
        self.scroll_area.verticalScrollBar().setValue(target_y)

    def set_highlight_mode(self, active: bool):
        for pv in self.page_views:
            pv.highlight_mode = active

    def clear_search_highlights(self):
        """Remove all temporary Target Reading search highlights."""
        for pv in self.page_views:
            pv.clear_search_highlights()

    def eventFilter(self, watched, event):
        if watched == self.scroll_area.viewport() and event.type() == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y() / 1200.0
                if delta != 0:
                    self._pending_zoom_delta += delta
                    self._zoom_timer.start(80)
                return True
        return super().eventFilter(watched, event)

    def _commit_zoom(self):
        if self._pending_zoom_delta != 0:
            self.request_zoom.emit(self._pending_zoom_delta)
            self._pending_zoom_delta = 0.0
