"""
Custom widgets for PDF page rendering and word-level interaction.
"""
import random
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QWidget, QLabel, QSizePolicy, QApplication
)

from core.pdf_engine import PdfEngine
from core.logger import get_logger
from core.theme_colors import get_theme_colors

logger = get_logger()


class WordWidget(QWidget):
    """
    Transparent interactive widget placed over a word on the PDF page.
    Handles Mask Mode reveal/hide, Vocab Mode hover collection,
    and text selection with press-drag-release.
    """
    hovered = Signal(str, int, int, int)  # text, page, block, line
    clicked = Signal(str, int, int, int)

    def __init__(
        self,
        text: str,
        page: int,
        block: int,
        line: int,
        x: float,
        y: float,
        width: float,
        height: float,
        parent=None
    ):
        super().__init__(parent)
        self.text = text
        self.page = page
        self.block = block
        self.line = line
        self.setGeometry(int(x), int(y), int(width) + 1, int(height) + 1)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self.mask_enabled = False
        self.revealed = False
        self.collected = False
        self.selected = False

    def set_mask_enabled(self, enabled: bool):
        self.mask_enabled = enabled
        self.revealed = False
        self.update()

    def set_revealed(self, revealed: bool):
        if not self.mask_enabled:
            return
        self.revealed = revealed
        self.update()

    def set_collected(self, collected: bool):
        self.collected = collected
        self.update()

    def set_selected(self, selected: bool):
        self.selected = selected
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.mask_enabled and not self.revealed:
            painter.fillRect(self.rect(), QColor(30, 30, 30))
        elif self.selected:
            pv = self._get_page_view()
            if pv and pv.highlight_mode:
                # Highlight mode: brighter selection with glow border
                painter.fillRect(self.rect(), QColor(100, 200, 255, 220))
                pen = painter.pen()
                pen.setColor(QColor(255, 255, 255, 200))
                pen.setWidth(1)
                painter.setPen(pen)
                painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
            else:
                painter.fillRect(self.rect(), QColor(66, 165, 245, 180))
        elif self.collected:
            painter.fillRect(self.rect(), QColor(255, 235, 59, 120))
        else:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
        painter.end()

    def enterEvent(self, event):
        if self.mask_enabled:
            self.set_revealed(True)
        self.hovered.emit(self.text, self.page, self.block, self.line)
        # Show saved explanation tooltip on hover
        pv = self._get_page_view()
        if pv and pv.engine and pv.engine.path:
            from core import database
            explanation = database.get_explanation(pv.engine.path, self.text)
            if explanation:
                self.setToolTip(f"💡 {explanation}")
            else:
                self.setToolTip("")
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.mask_enabled:
            self.set_revealed(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._handle_press()
        self.clicked.emit(self.text, self.page, self.block, self.line)
        event.accept()  # ensure mouse grab so we receive move/release even when cursor leaves

    def mouseMoveEvent(self, event):
        page_view = self._get_page_view()
        if page_view and page_view.selection_active:
            target = page_view.widget_at_global(event.globalPosition().toPoint())
            if target and isinstance(target, WordWidget):
                page_view.add_to_selection(target)
        event.accept()

    def mouseReleaseEvent(self, event):
        page_view = self._get_page_view()
        if page_view and page_view.selection_active:
            page_view.finish_selection(event.globalPosition().toPoint())
        event.accept()

    def _handle_press(self):
        page_view = self._get_page_view()
        if not page_view:
            return
        if page_view.selected_widgets and self not in page_view.selected_widgets:
            page_view.clear_selection()
            return
        if not page_view.selected_widgets:
            page_view.start_selection(self)

    def _get_page_view(self):
        parent = self.parent()
        while parent:
            if isinstance(parent, PageView):
                return parent
            parent = parent.parent()
        return None


class ImageHitWidget(QWidget):
    """
    Transparent clickable overlay placed over an image region on the PDF page.
    Emits image_clicked when the user clicks on the image area.
    Shows a blue border after being clicked (selected).
    """
    image_clicked = Signal(int, int)  # page_number, image_index

    def __init__(self, page_number: int, image_index: int, x: float, y: float, width: float, height: float, parent=None):
        super().__init__(parent)
        self.page_number = page_number
        self.image_index = image_index
        self.setGeometry(int(x), int(y), int(width) + 1, int(height) + 1)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._selected = False


    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool):
        self._selected = selected
        self.update()

    def paintEvent(self, event):
        if self._selected:
            painter = QPainter(self)
            pen = painter.pen()
            pen.setColor(QColor(66, 165, 245))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawRect(self.rect().adjusted(1, 1, -1, -1))
            painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.image_clicked.emit(self.page_number, self.image_index)
        event.accept()


class LinkWidget(QWidget):
    """
    Transparent clickable overlay placed over a hyperlink region on the PDF page.
    Emits link_clicked with link data dict when clicked.
    """
    link_clicked = Signal(dict)

    def __init__(self, link_data: dict, x: float, y: float, width: float, height: float, parent=None):
        super().__init__(parent)
        self.link_data = link_data
        self.setGeometry(int(x), int(y), int(width) + 1, int(height) + 1)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        # Tooltip shows target info
        kind = self.link_data.get("kind", "")
        if kind == "goto":
            page = self.link_data.get("target_page", -1)
            self.setToolTip(f"Go to page {page + 1}")
        elif kind == "uri":
            uri = self.link_data.get("uri", "")[:60]
            self.setToolTip(f"Open: {uri}...")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        if self._hovered:
            painter = QPainter(self)
            pen = painter.pen()
            pen.setColor(QColor(66, 165, 245))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRect(self.rect().adjusted(1, 1, -1, -1))
            painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.link_clicked.emit(self.link_data)
        event.accept()


class HighlightWidget(QWidget):
    """
    Visual overlay showing a persistent text highlight.
    Receives mouse events for click-to-select, right-click delete/copy,
    and keyboard shortcuts (Ctrl+C).
    """
    highlight_deleted = Signal(int)
    highlight_selected = Signal(int)
    highlight_copied = Signal(str)

    def __init__(self, highlight_id: int, color: str, x: float, y: float, width: float, height: float, text: str = "", parent=None):
        super().__init__(parent)
        self.highlight_id = highlight_id
        self.color = color
        self.text = text
        self.setGeometry(int(x), int(y), int(width) + 1, int(height) + 1)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._hovered = False
        self._selected = False

    def set_selected(self, selected: bool):
        self._selected = selected
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        c = QColor(self.color)
        c.setAlpha(160 if self._selected else (140 if self._hovered else 100))
        painter.fillRect(self.rect(), c)

        if self._selected:
            colors = get_theme_colors()
            selected_color = QColor(colors.get("selected", "#3a5a8a"))
            # Outer glow / shadow for stronger visual feedback
            glow = QColor(selected_color)
            glow.setAlpha(80)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawRect(self.rect().adjusted(-2, -2, 2, 2))
            # Solid border inside widget bounds
            pen = QPen(selected_color)
            pen.setWidth(2)
            pen.setStyle(Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(2, 2, -2, -2))
        elif self._hovered:
            pen = QPen(QColor(255, 255, 255, 180))
            pen.setWidth(1)
            pen.setStyle(Qt.PenStyle.DotLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(1, 1, -1, -1))
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.set_selected(True)
            self.setFocus()
            self.highlight_selected.emit(self.highlight_id)
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            from PySide6.QtWidgets import QMenu
            menu = QMenu(self)
            colors = get_theme_colors()
            bg = colors.get("bg", "#333333")
            text = colors.get("text", "#eeeeee")
            border = colors.get("border", "#555555")
            hover = colors.get("hover", "#444444")
            menu.setStyleSheet(
                f"QMenu {{ background: {bg}; color: {text}; border: 1px solid {border}; }}"
                f"QMenu::item {{ padding: 6px 24px; }}"
                f"QMenu::item:selected {{ background: {hover}; }}"
            )
            act_copy = menu.addAction("📋 Copy")
            act_delete = menu.addAction("🗑️ Delete Highlight")
            action = menu.exec(event.globalPosition().toPoint())
            if action == act_copy:
                QApplication.clipboard().setText(self.text)
                self.highlight_copied.emit(self.text)
            elif action == act_delete:
                self.highlight_deleted.emit(self.highlight_id)
        event.accept()

    def keyPressEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_C:
            if self.text:
                QApplication.clipboard().setText(self.text)
                self.highlight_copied.emit(self.text)
            event.accept()
            return
        super().keyPressEvent(event)


class SearchHighlightWidget(QWidget):
    """
    Temporary visual overlay for Target Reading search results.
    Not persisted to the database; cleared when the mode is exited.
    """

    def __init__(self, x: float, y: float, width: float, height: float, active: bool = False, parent=None):
        super().__init__(parent)
        self.setGeometry(int(x), int(y), int(width) + 1, int(height) + 1)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._active = active

    def set_active(self, active: bool):
        self._active = active
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        # Amber/orange fill; stronger alpha when active
        fill = QColor(255, 152, 0)
        fill.setAlpha(180 if self._active else 100)
        painter.fillRect(self.rect(), fill)

        border = QColor(255, 87, 34)
        pen = QPen(border)
        pen.setWidth(3 if self._active else 1)
        pen.setStyle(Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = self.rect().adjusted(1, 1, -1, -1)
        if self._active:
            # Make sure the 3px border stays fully inside the widget
            rect = rect.adjusted(1, 1, -1, -1)
        painter.drawRect(rect)
        painter.end()


class PageView(QWidget):
    """
    Displays a single PDF page with an image background and an interactive
    text overlay composed of WordWidgets.
    """
    word_hovered = Signal(str, int, int, int)
    word_clicked = Signal(str, int, int, int)
    words_collected = Signal(list, int, str)  # list[str], page_number, context
    explain_requested = Signal(str, str, object)  # selected_text, context, global_pos (QPoint)
    image_clicked = Signal(int, int)  # page_number, image_index
    page_double_clicked = Signal(int)  # page_number
    link_clicked = Signal(dict)  # link data dict

    def __init__(self, engine: PdfEngine, page_number: int, zoom: float = 1.5, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.page_number = page_number
        self.zoom = zoom
        self.word_widgets: list[WordWidget] = []
        self.image_hit_widgets: list[ImageHitWidget] = []
        self.link_widgets: list[LinkWidget] = []
        self.highlight_widgets: list[HighlightWidget] = []
        self._selected_highlight: HighlightWidget | None = None
        self.search_highlight_widgets: list[SearchHighlightWidget] = []

        self.image_label = QLabel(self)
        self.image_label.setScaledContents(False)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.overlay = QWidget(self)
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.overlay.setStyleSheet("background: transparent;")
        # Click on empty area clears selection; double-click on empty area captures whole page
        self.overlay.mousePressEvent = self._on_overlay_press
        self.overlay.mouseDoubleClickEvent = self._on_overlay_double_click

        # Floating preview label that shows currently selected text
        self.selection_preview = QLabel(self.overlay)
        self.selection_preview.setStyleSheet(
            "QLabel { background: rgba(0, 0, 0, 200); color: #ffffff; "
            "border-radius: 4px; padding: 4px 8px; font-size: 13px; }"
        )
        self.selection_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.selection_preview.hide()

        self.selection_active = False
        self.selected_widgets: set[WordWidget] = set()
        self.vocab_mode = False
        self.explain_mode = False
        self.highlight_mode = False
        self._image_dirty = False

        self.load_page()

    def _on_overlay_press(self, event):
        local_pos = event.pos()
        for w in self.word_widgets:
            if w.geometry().contains(local_pos):
                self.clear_image_selections()
                return
        for iw in self.image_hit_widgets:
            if iw.geometry().contains(local_pos):
                return
        for lw in self.link_widgets:
            if lw.geometry().contains(local_pos):
                return
        for hw in self.highlight_widgets:
            if hw.geometry().contains(local_pos):
                return
        self.clear_image_selections()
        if self.selected_widgets:
            self.clear_selection()
        self._clear_highlight_selection()


    def _on_overlay_double_click(self, event):
        # Only trigger if not clicking on a word widget, image hit widget, or link widget
        local_pos = event.pos()
        for w in self.word_widgets:
            if w.geometry().contains(local_pos):
                return
        for iw in self.image_hit_widgets:
            if iw.geometry().contains(local_pos):
                return
        for lw in self.link_widgets:
            if lw.geometry().contains(local_pos):
                return
        self.page_double_clicked.emit(self.page_number)
        event.accept()

    def load_page(self):
        image = self.engine.render_page(self.page_number, self.zoom)
        if image is None:
            return
        pixmap = QPixmap.fromImage(image)
        self.image_label.setPixmap(pixmap)
        self.image_label.resize(pixmap.width(), pixmap.height())
        self.overlay.setGeometry(0, 0, pixmap.width(), pixmap.height())
        self.overlay.raise_()
        self.setFixedSize(pixmap.width(), pixmap.height())
        self._build_word_widgets()
        self._build_image_hit_widgets()
        self._build_link_widgets()
        self._load_highlights()

    def rescale(self, new_zoom: float, render_image: bool = True):
        """Resize page and word widgets without destroying them."""
        if not self.engine or new_zoom == self.zoom:
            return
        self.zoom = new_zoom
        self._update_geometry()
        self._update_word_widgets()
        self._update_image_hit_widgets()
        self._update_link_widgets()
        self._update_highlight_widgets()
        if render_image:
            self._render_image()
        self.overlay.raise_()

    def _update_geometry(self):
        """Update sizes based on page rect without rendering."""
        page = self.engine.doc.load_page(self.page_number)
        w = int(page.rect.width * self.zoom)
        h = int(page.rect.height * self.zoom)
        self.image_label.resize(w, h)
        self.overlay.setGeometry(0, 0, w, h)
        self.setFixedSize(w, h)

    def _render_image(self):
        image = self.engine.render_page(self.page_number, self.zoom)
        if image is None:
            return
        pixmap = QPixmap.fromImage(image)
        self.image_label.setPixmap(pixmap)
        self._image_dirty = False
        self.overlay.raise_()

    def _build_word_widgets(self):
        for w in self.word_widgets:
            w.setParent(None)
            w.deleteLater()
        self.word_widgets.clear()
        self.selected_widgets.clear()
        self.selection_active = False
        self.selection_preview.hide()

        words = self.engine.get_page_words(self.page_number, self.zoom)
        for wd in words:
            if wd["width"] < 2 or wd["height"] < 2:
                continue
            ww = WordWidget(
                text=wd["text"],
                page=wd["page"],
                block=wd.get("block", 0),
                line=wd.get("line", 0),
                x=wd["x"],
                y=wd["y"],
                width=wd["width"],
                height=wd["height"],
                parent=self.overlay,
            )
            ww.hovered.connect(self.word_hovered)
            ww.clicked.connect(self.word_clicked)
            ww.show()
            self.word_widgets.append(ww)

    def _update_word_widgets(self):
        """Update geometry of existing word widgets after zoom change."""
        words = self.engine.get_page_words(self.page_number, self.zoom)
        # Match by index (reading order is stable across zoom levels)
        for i, ww in enumerate(self.word_widgets):
            if i < len(words):
                wd = words[i]
                ww.setGeometry(int(wd["x"]), int(wd["y"]), int(wd["width"]) + 1, int(wd["height"]) + 1)
                if not ww.isVisible():
                    ww.show()
            else:
                ww.hide()

        for wd in words[len(self.word_widgets):]:
            if wd["width"] < 2 or wd["height"] < 2:
                continue
            ww = WordWidget(
                text=wd["text"],
                page=wd["page"],
                block=wd.get("block", 0),
                line=wd.get("line", 0),
                x=wd["x"],
                y=wd["y"],
                width=wd["width"],
                height=wd["height"],
                parent=self.overlay,
            )
            ww.hovered.connect(self.word_hovered)
            ww.clicked.connect(self.word_clicked)
            self.word_widgets.append(ww)

    def _build_image_hit_widgets(self):
        for iw in self.image_hit_widgets:
            iw.setParent(None)
            iw.deleteLater()
        self.image_hit_widgets.clear()

        images = self.engine.get_page_images(self.page_number, self.zoom)
        for img in images:
            if img["width"] < 5 or img["height"] < 5:
                continue
            iw = ImageHitWidget(
                page_number=self.page_number,
                image_index=img["index"],
                x=img["x"],
                y=img["y"],
                width=img["width"],
                height=img["height"],
                parent=self.overlay,
            )
            iw.image_clicked.connect(self.image_clicked)
            iw.show()
            self.image_hit_widgets.append(iw)

    def _update_image_hit_widgets(self):
        """Rebuild image hit widgets after zoom change (simpler than matching by index)."""
        self._build_image_hit_widgets()

    def widget_at_global(self, global_pos):
        """Find WordWidget under global cursor position using geometry."""
        local_pos = self.overlay.mapFromGlobal(global_pos)
        for w in self.word_widgets:
            if w.geometry().contains(local_pos):
                return w
        return None

    def start_selection(self, widget: WordWidget):
        self.clear_selection()
        self.selection_active = True
        widget.set_selected(True)
        self.selected_widgets.add(widget)
        self._update_selection_preview()

    def add_to_selection(self, widget: WordWidget):
        if widget not in self.selected_widgets:
            widget.set_selected(True)
            self.selected_widgets.add(widget)
            self._update_selection_preview()

    def finish_selection(self, global_pos):
        self.selection_active = False
        if not self.selected_widgets:
            return

        if self.vocab_mode:
            texts = self._sorted_selected_texts()
            # Immediately mark selected widgets as collected (yellow) for visual feedback
            for w in self.selected_widgets:
                w.set_collected(True)

            # Extract context from the line of the first selected word
            context = ""
            sorted_widgets = sorted(self.selected_widgets, key=lambda w: (w.y(), w.x()))
            if sorted_widgets:
                first = sorted_widgets[0]
                context = self.engine.get_line_context(first.page, first.block, first.line)

            if len(texts) == 1:
                # Single click -> word
                self.words_collected.emit(texts, self.page_number, context)
            else:
                # Drag across multiple words -> phrase / sentence
                joined = " ".join(texts)
                self.words_collected.emit([joined], self.page_number, context)
            self.clear_selection()
        elif self.explain_mode:
            texts = self._sorted_selected_texts()
            joined = " ".join(texts)
            context = ""
            sorted_widgets = sorted(self.selected_widgets, key=lambda w: (w.y(), w.x()))
            if sorted_widgets:
                first = sorted_widgets[0]
                context = self.engine.get_line_context(first.page, first.block, first.line)
            global_point = self.mapToGlobal(global_pos.toPoint() if hasattr(global_pos, 'toPoint') else global_pos)
            self.explain_requested.emit(joined, context, global_point)
            self.clear_selection()
        elif self.highlight_mode:
            # Show color picker popup at selection center
            sorted_widgets = sorted(self.selected_widgets, key=lambda w: (w.y(), w.x()))
            if sorted_widgets:
                first = sorted_widgets[0]
                last = sorted_widgets[-1]
                cx = (first.x() + last.x() + last.width()) // 2
                cy = (first.y() + last.y() + last.height()) // 2
                global_point = self.overlay.mapToGlobal(self.overlay.rect().center())
                global_point = self.mapToGlobal(self.rect().center())
                # Use a simpler position: above the first selected word
                popup_pos = self.mapToGlobal(first.geometry().center())
                self._show_highlight_popup(popup_pos)
        else:
            # Normal mode: keep selection alive, no popup menu
            pass

    def _show_highlight_popup(self, global_pos):
        from ui.highlight_popup import HighlightPopup
        popup = HighlightPopup(self)

        def _on_color(color: str):
            self._apply_highlight(color)

        popup.color_selected.connect(_on_color)
        popup.show_at(global_pos)

    def _apply_highlight(self, color: str):
        if not self.selected_widgets or not self.engine or not self.engine.path:
            return
        sorted_widgets = sorted(self.selected_widgets, key=lambda w: (w.y(), w.x()))
        if not sorted_widgets:
            return
        # Compute bounding box of selection
        x0 = min(w.x() for w in sorted_widgets)
        y0 = min(w.y() for w in sorted_widgets)
        x1 = max(w.x() + w.width() for w in sorted_widgets)
        y1 = max(w.y() + w.height() for w in sorted_widgets)
        texts = " ".join(w.text for w in sorted_widgets)
        # Save to DB
        from core import database
        hid = database.save_highlight(
            self.engine.path, self.page_number, texts,
            x0 / self.zoom, y0 / self.zoom, (x1 - x0) / self.zoom, (y1 - y0) / self.zoom,
            color
        )
        # Create widget
        hw = HighlightWidget(hid, color, x0, y0, x1 - x0, y1 - y0, parent=self.overlay)
        hw.highlight_deleted.connect(self._on_highlight_deleted)
        hw.show()
        self.highlight_widgets.append(hw)
        self.clear_selection()

    def clear_image_selections(self):
        for iw in self.image_hit_widgets:
            iw.set_selected(False)

    def clear_selection(self):
        self.selection_active = False
        for w in self.selected_widgets:
            w.set_selected(False)
        self.selected_widgets.clear()
        self.selection_preview.hide()
        self.clear_image_selections()

    def _update_selection_preview(self):
        if not self.selected_widgets:
            self.selection_preview.hide()
            return
        texts = self._sorted_selected_texts()
        preview_text = " ".join(texts)
        self.selection_preview.setText(preview_text)

        # Position preview above the first selected word
        sorted_widgets = sorted(self.selected_widgets, key=lambda w: (w.y(), w.x()))
        first = sorted_widgets[0]
        x = first.x()
        y = max(0, first.y() - 30)
        self.selection_preview.move(x, y)
        self.selection_preview.adjustSize()
        self.selection_preview.show()
        self.selection_preview.raise_()

    def get_selected_text(self) -> str:
        texts = self._sorted_selected_texts()
        return " ".join(texts)

    def _sorted_selected_texts(self) -> list[str]:
        sorted_widgets = sorted(self.selected_widgets, key=lambda w: (w.y(), w.x()))
        return [w.text for w in sorted_widgets]

    def apply_mask_mode(self, active: bool, ratio: float = 0.35):
        if not self.word_widgets:
            return
        try:
            if active:
                count = int(len(self.word_widgets) * ratio)
                count = max(0, min(count, len(self.word_widgets)))
                if count > 0:
                    chosen = random.sample(self.word_widgets, count)
                    for ww in self.word_widgets:
                        ww.set_mask_enabled(ww in chosen)
                else:
                    for ww in self.word_widgets:
                        ww.set_mask_enabled(False)
            else:
                for ww in self.word_widgets:
                    ww.set_mask_enabled(False)
        except Exception:
            pass

    def mark_word_collected(self, text: str):
        for ww in self.word_widgets:
            if ww.text.lower() == text.lower():
                ww.set_collected(True)

    def unmark_word_collected(self, text: str):
        for ww in self.word_widgets:
            if ww.text.lower() == text.lower():
                ww.set_collected(False)

    def clear_collected_marks(self):
        for ww in self.word_widgets:
            ww.set_collected(False)

    # ------------------------------------------------------------------ #
    # Link widgets
    # ------------------------------------------------------------------ #

    def _build_link_widgets(self):
        for lw in self.link_widgets:
            lw.setParent(None)
            lw.deleteLater()
        self.link_widgets.clear()

        links = self.engine.get_page_links(self.page_number, self.zoom)
        for link in links:
            if link["width"] < 2 or link["height"] < 2:
                continue
            lw = LinkWidget(
                link_data=link,
                x=link["x"],
                y=link["y"],
                width=link["width"],
                height=link["height"],
                parent=self.overlay,
            )
            lw.link_clicked.connect(self.link_clicked)
            lw.show()
            self.link_widgets.append(lw)

    def _update_link_widgets(self):
        """Rebuild link widgets after zoom change."""
        self._build_link_widgets()

    # ------------------------------------------------------------------ #
    # Highlight widgets
    # ------------------------------------------------------------------ #

    def _load_highlights(self):
        """Load persistent highlights from DB for this page."""
        for hw in self.highlight_widgets:
            hw.setParent(None)
            hw.deleteLater()
        self.highlight_widgets.clear()
        self._selected_highlight = None

        if not self.engine or not self.engine.path:
            return
        from core import database
        highlights = database.get_highlights_by_pdf(self.engine.path)
        for h in highlights:
            if h["page_number"] != self.page_number:
                continue
            hw = HighlightWidget(
                highlight_id=h["id"],
                color=h["color"],
                x=h["x"] * self.zoom,
                y=h["y"] * self.zoom,
                width=h["width"] * self.zoom,
                height=h["height"] * self.zoom,
                text=h.get("text", ""),
                parent=self.overlay,
            )
            hw.highlight_deleted.connect(self._on_highlight_deleted)
            hw.highlight_selected.connect(self._on_highlight_selected)
            hw.show()
            self.highlight_widgets.append(hw)

    def _on_highlight_selected(self, highlight_id: int):
        """Mutually exclusive highlight selection."""
        for hw in self.highlight_widgets:
            if hw.highlight_id != highlight_id:
                hw.set_selected(False)
            else:
                self._selected_highlight = hw

    def _clear_highlight_selection(self):
        for hw in self.highlight_widgets:
            hw.set_selected(False)
        self._selected_highlight = None

    def _on_highlight_deleted(self, highlight_id: int):
        from core import database
        database.delete_highlight(highlight_id)
        self._load_highlights()

    def _update_highlight_widgets(self):
        """Rebuild highlight widgets after zoom change."""
        self._load_highlights()

    # ------------------------------------------------------------------ #
    # Search highlights (Target Reading mode)
    # ------------------------------------------------------------------ #

    def clear_search_highlights(self):
        """Remove all temporary search-highlight widgets."""
        for w in self.search_highlight_widgets:
            w.setParent(None)
            w.deleteLater()
        self.search_highlight_widgets.clear()

    def highlight_search_results(self, quote: str, active: bool = False) -> bool:
        """
        Highlight the first occurrence of *quote* on this page.
        Returns True if a match was found and highlighted.
        """
        if not self.word_widgets or not quote:
            return False
        quote = quote.strip()
        # Try exact substring match across word texts first
        texts = [w.text for w in self.word_widgets]
        n = len(self.word_widgets)
        matched_widgets = []
        for i in range(n):
            for j in range(i + 1, min(n, i + 40) + 1):
                snippet = " ".join(texts[i:j])
                if quote in snippet:
                    matched_widgets = self.word_widgets[i:j]
                    break
            if matched_widgets:
                break

        if not matched_widgets:
            # Fallback: try matching any contiguous words that together contain
            # at least half of the quote words in order.
            quote_words = quote.split()
            if len(quote_words) <= 1:
                return False
            for i in range(n):
                acc = []
                for j in range(i, min(n, i + 40)):
                    acc.append(self.word_widgets[j].text)
                    joined = " ".join(acc)
                    if quote in joined or joined in quote:
                        matched_widgets = self.word_widgets[i:j + 1]
                        break
                if matched_widgets:
                    break

        if not matched_widgets:
            return False

        sorted_widgets = sorted(matched_widgets, key=lambda w: (w.y(), w.x()))
        x0 = min(w.x() for w in sorted_widgets)
        y0 = min(w.y() for w in sorted_widgets)
        x1 = max(w.x() + w.width() for w in sorted_widgets)
        y1 = max(w.y() + w.height() for w in sorted_widgets)

        w = SearchHighlightWidget(x0, y0, x1 - x0, y1 - y0, active=active, parent=self.overlay)
        w.show()
        self.search_highlight_widgets.append(w)
        return True

    def set_active_search_highlight(self, active_widget: SearchHighlightWidget | None):
        """Mark one search highlight as active and others inactive."""
        for w in self.search_highlight_widgets:
            w.set_active(w is active_widget)
