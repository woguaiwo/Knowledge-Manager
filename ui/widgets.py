"""
Custom widgets for PDF page rendering and word-level interaction.
"""
import random
import re
import math
import json
from PySide6.QtCore import Qt, Signal, QRect, QPoint, QSize, QEvent
from PySide6.QtGui import QColor, QPainter, QPixmap, QPen, QTextDocument
from PySide6.QtWidgets import (
    QWidget, QLabel, QSizePolicy, QApplication, QTextBrowser, QFrame
)

from core.pdf_engine import PdfEngine
from core.logger import get_logger
from core.theme_colors import get_theme_colors


def _get_hover_label_style() -> str:
    """Return theme-adaptive stylesheet for hover labels."""
    colors = get_theme_colors()
    # Use base color for background, text color for text
    # This ensures proper contrast in both light and dark themes
    bg = colors.get("base", "#333333")
    text = colors.get("text", "#ffffff")
    border = colors.get("border", "#555555")
    return (
        "QLabel, QTextBrowser {"
        f"background: {bg};"
        f"color: {text};"
        f"border: 1px solid {border};"
        "border-radius: 4px;"
        "padding: 6px 10px;"
        "font-size: 12px;"
        "}"
        "QTextBrowser {"
        "padding: 6px 10px;"
        "}"
        "QTextBrowser QScrollBar:vertical {"
        "width: 10px;"
        "margin: 2px;"
        "}"
    )


_HOVER_LABEL_MAX_WIDTH = 270
_HOVER_LABEL_MAX_HEIGHT = 360
_HOVER_LABEL_MARGIN = 8
_HOVER_LABEL_MIN_WIDTH = 120
_HOVER_LABEL_MIN_HEIGHT = 60


def _looks_like_markdown(text: str) -> bool:
    """Detect clear Markdown markers without classifying ordinary prose as rich text."""
    if not text or not text.strip():
        return False

    lines = text.splitlines()
    marker_patterns = (
        r"^\s{0,3}#{1,6}\s+\S+",       # headings
        r"^\s*[-*+]\s+\S+",            # unordered lists
        r"^\s*\d+[.)]\s+\S+",         # ordered lists
        r"^\s*>\s+\S+",                # block quotes
        r"^\s*```",                     # fenced code
        r"^\s*\|.+\|\s*$",             # tables
        r"^\s{4,}\S+",                 # indented code blocks
        r"^\s*(?:[-*_]\s*){3,}$",      # horizontal rules
        r"^\s*=+\s*$",                  # setext heading underline
    )
    if any(re.search(pattern, line) for line in lines for pattern in marker_patterns):
        return True

    inline_patterns = (
        r"\[[^\]]+\]\([^\)]+\)",       # links
        r"`[^`\n]+`",                     # inline code
        r"(?:\*\*|__)[^\n]+?(?:\*\*|__)",  # bold
        r"(?<!\*)\*[^*\n]+\*(?!\*)",  # italic
    )
    return any(re.search(pattern, text) for pattern in inline_patterns)


def _render_hover_text(text: str, note_format: str = "auto") -> tuple[str, Qt.TextFormat]:
    """Return label text and its Qt format, rendering Markdown only when needed."""
    format_name = (note_format or "auto").strip().lower()
    use_markdown = format_name == "markdown" or (
        format_name not in {"plain", "text"} and _looks_like_markdown(text)
    )
    if not use_markdown:
        return text, Qt.TextFormat.PlainText

    document = QTextDocument()
    document.setMarkdown(text)
    return document.toHtml(), Qt.TextFormat.RichText


def _load_hover_size() -> QSize | None:
    """Read the user's preferred hover size, if one has been saved."""
    try:
        from core import database
        raw = database.get_setting("annotation_hover_size", "")
        if raw:
            data = json.loads(raw)
            width = int(data.get("width", 0))
            height = int(data.get("height", 0))
            if width > 0 and height > 0:
                return QSize(width, height)
    except (ValueError, TypeError, json.JSONDecodeError):
        pass
    return None


def _save_hover_size(width: int, height: int):
    """Persist a user-resized hover window for future annotations."""
    try:
        from core import database
        database.save_setting(
            "annotation_hover_size",
            json.dumps({"width": int(width), "height": int(height)}),
        )
    except Exception as exc:
        logger.debug("Could not persist annotation hover size: %s", exc)


class HoverTextBrowser(QTextBrowser):
    """Scrollable hover viewer with a bottom-right resize handle."""

    resize_finished = Signal(int, int)
    _RESIZE_HANDLE_SIZE = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._resizing = False
        self._resize_origin = None
        self._resize_start_size = None
        self._user_resized = False
        self._resize_enabled = False
        self._app_filter_installed = False
        # The grip owns the innermost part of the resize corner.  The
        # surrounding viewport/scrollbar filters below cover the remaining
        # few pixels, which also makes the handle reliable over Qt's scroll
        # bar corner widget.
        self._resize_grip = _HoverResizeGrip(self)
        self._resize_grip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._resize_grip.show()
        # QAbstractScrollArea's viewport does not report passive mouse moves
        # by default.  Enable tracking on every child that can be underneath
        # the pointer so the diagonal resize cursor appears before pressing.
        self.viewport().setMouseTracking(True)
        self.verticalScrollBar().setMouseTracking(True)
        self.horizontalScrollBar().setMouseTracking(True)
        self.viewport().installEventFilter(self)
        self.verticalScrollBar().installEventFilter(self)
        self.horizontalScrollBar().installEventFilter(self)

    def _set_child_cursor(self, shape):
        """Apply a cursor to every scroll-area child that may be under it."""
        self.setCursor(shape)
        self.viewport().setCursor(shape)
        self.verticalScrollBar().setCursor(shape)
        self.horizontalScrollBar().setCursor(shape)
        if self._resize_grip is not None:
            self._resize_grip.setCursor(shape)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._resize_grip is not None:
            size = self._resize_grip.sizeHint().width()
            self._resize_grip.setGeometry(self.width() - size, self.height() - size, size, size)
            self._resize_grip.raise_()

    def set_resize_enabled(self, enabled: bool):
        """Enable the resize handle only while the viewer is pinned."""
        enabled = bool(enabled)
        if not enabled and self._resizing:
            # A pinned viewer can be unpinned while a drag is in progress.
            # Always release the mouse grab before hiding it, otherwise Qt
            # keeps routing all page events to this invisible child.
            self._finish_resize()
        self._resize_enabled = enabled
        app = QApplication.instance()
        if enabled:
            if app is not None and not self._app_filter_installed:
                app.installEventFilter(self)
                self._app_filter_installed = True
        elif app is not None and self._app_filter_installed:
            app.removeEventFilter(self)
            self._app_filter_installed = False
        if self._resize_grip is not None:
            self._resize_grip.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, not enabled
            )
            self._resize_grip.setCursor(
                Qt.CursorShape.SizeFDiagCursor if enabled else Qt.CursorShape.ArrowCursor
            )
            self._resize_grip.raise_()
        self._set_child_cursor(Qt.CursorShape.ArrowCursor)
        if enabled and self._resize_grip is not None:
            # _set_child_cursor also updates the grip; restore its persistent
            # resize cursor after applying the normal arrow to the browser.
            self._resize_grip.setCursor(Qt.CursorShape.SizeFDiagCursor)

    def _in_resize_handle(self, pos) -> bool:
        """Return whether *pos* (in this widget's coordinates) is in the grip."""
        return (
            pos.x() >= self.width() - self._RESIZE_HANDLE_SIZE
            and pos.y() >= self.height() - self._RESIZE_HANDLE_SIZE
        )

    def _global_in_resize_handle(self, global_pos) -> bool:
        return self._in_resize_handle(self.mapFromGlobal(global_pos))

    def _update_resize_cursor(self, global_pos):
        if self._resize_enabled and self._global_in_resize_handle(global_pos):
            self._set_child_cursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self._set_child_cursor(Qt.CursorShape.ArrowCursor)
        # Keep the actual handle's cursor independent of whichever child
        # (viewport or scrollbar) last reported a move.  This avoids a stale
        # arrow when the pointer re-enters the corner without crossing the
        # viewport boundary.
        if self._resize_enabled and self._resize_grip is not None:
            self._resize_grip.setCursor(Qt.CursorShape.SizeFDiagCursor)

    def _start_resize(self, global_pos):
        if not self._resize_enabled or self._resizing:
            return
        self._resizing = True
        self._resize_origin = global_pos
        self._resize_start_size = self.size()
        self._set_child_cursor(Qt.CursorShape.SizeFDiagCursor)
        # The application-level event filter below continues to receive move
        # and release events after the pointer leaves this child.  Avoid
        # QWidget.grabMouse(): on Windows a native mouse grab can keep all
        # page input routed to the hover widget when a release is missed.
        app = QApplication.instance()
        if app is not None and not self._app_filter_installed:
            app.installEventFilter(self)
            self._app_filter_installed = True

    def _resize_to(self, global_pos):
        if not self._resizing or self._resize_origin is None or self._resize_start_size is None:
            return
        # Do not use QApplication.mouseButtons() as a drag-state gate here.
        # On Windows, after a child widget starts a mouse grab this value can
        # briefly be empty while a MouseMove event is still being delivered.
        # Treating that transient state as a release made real drags appear to
        # do nothing.  The application-level event filter below owns the
        # release path and always calls _finish_resize on MouseButtonRelease
        # or deactivation.
        delta = global_pos - self._resize_origin
        parent = self.parentWidget()
        min_width = max(_HOVER_LABEL_MIN_WIDTH, self.minimumWidth())
        min_height = max(_HOVER_LABEL_MIN_HEIGHT, self.minimumHeight())
        max_width = self._resize_start_size.width() + delta.x()
        max_height = self._resize_start_size.height() + delta.y()
        if parent is not None:
            top_left = self.mapTo(parent, QPoint(0, 0))
            max_width = min(max_width, parent.width() - top_left.x() - _HOVER_LABEL_MARGIN)
            max_height = min(max_height, parent.height() - top_left.y() - _HOVER_LABEL_MARGIN)
        width = max(min_width, int(max_width))
        height = max(min_height, int(max_height))
        self.resize(width, height)

    def _finish_resize(self, global_pos=None):
        if not self._resizing:
            return
        self._resizing = False
        self._resize_origin = None
        self._resize_start_size = None
        self._user_resized = True
        self._set_child_cursor(Qt.CursorShape.ArrowCursor)
        if self._resize_enabled and self._resize_grip is not None:
            self._resize_grip.setCursor(Qt.CursorShape.SizeFDiagCursor)
            if global_pos is not None and self._global_in_resize_handle(global_pos):
                self._set_child_cursor(Qt.CursorShape.SizeFDiagCursor)
        self.resize_finished.emit(self.width(), self.height())

    def eventFilter(self, watched, event):
        app = QApplication.instance()
        if watched is app:
            event_type = event.type()
            if self._resizing and event_type == QEvent.Type.MouseMove:
                self._resize_to(event.globalPosition().toPoint())
                # The owner has a mouse grab, so consume the move here.  This
                # keeps the resize path independent of which QTextBrowser
                # child (viewport, scrollbar, or corner widget) owns it.
                return True
            if self._resizing and event_type == QEvent.Type.MouseButtonRelease:
                self._finish_resize(event.globalPosition().toPoint())
                return True
            if self._resizing and event_type in (
                QEvent.Type.WindowDeactivate,
                QEvent.Type.ApplicationDeactivate,
            ):
                self._finish_resize()
                return True
            if self._resize_enabled and event_type == QEvent.Type.MouseMove:
                self._update_resize_cursor(event.globalPosition().toPoint())
                return False
            if (
                self._resize_enabled
                and event_type == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                global_pos = event.globalPosition().toPoint()
                if self._global_in_resize_handle(global_pos):
                    self._start_resize(global_pos)
                    return True
            return False
        if watched in (self.viewport(), self.verticalScrollBar(), self.horizontalScrollBar()):
            event_type = event.type()
            if event_type == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                global_pos = event.globalPosition().toPoint()
                if self._resize_enabled and self._global_in_resize_handle(global_pos):
                    self._start_resize(global_pos)
                    return True
            elif event_type == QEvent.Type.MouseMove and self._resizing:
                self._resize_to(event.globalPosition().toPoint())
                return True
            elif event_type == QEvent.Type.MouseButtonRelease and self._resizing:
                self._finish_resize()
                return True
            elif event_type == QEvent.Type.MouseMove and self._resize_enabled:
                self._update_resize_cursor(event.globalPosition().toPoint())
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._resize_enabled
            and self._in_resize_handle(event.position().toPoint())
        ):
            self._start_resize(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing and self._resize_origin is not None and self._resize_start_size is not None:
            self._resize_to(event.globalPosition().toPoint())
            event.accept()
            return

        if self._resize_enabled:
            self._update_resize_cursor(event.globalPosition().toPoint())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing and event.button() == Qt.MouseButton.LeftButton:
            self._finish_resize()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def hideEvent(self, event):
        # A pinned viewer can be hidden while a resize gesture is active
        # (for example when its icon is unpinned). Finish the gesture before
        # the widget disappears so no pending resize state survives.
        if self._resizing:
            self._finish_resize()
        super().hideEvent(event)

    def focusOutEvent(self, event):
        if self._resizing:
            self._finish_resize()
        super().focusOutEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)


class _HoverResizeGrip(QWidget):
    """Small child widget that keeps resize events out of QTextBrowser's viewport."""

    def __init__(self, owner: HoverTextBrowser):
        super().__init__(owner)
        self.owner = owner
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

    def sizeHint(self):
        return QSize(18, 18)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.owner._start_resize(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.owner._resizing:
            self.owner._resize_to(event.globalPosition().toPoint())
            event.accept()
            return
        if self.owner._resize_enabled:
            self.owner._update_resize_cursor(event.globalPosition().toPoint())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.owner._resizing:
            self.owner._finish_resize()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        colors = get_theme_colors()
        pen = QPen(QColor(colors.get("border", "#777777")))
        pen.setWidth(1)
        painter.setPen(pen)
        x = self.width() - 4
        y = self.height() - 4
        painter.drawLine(x - 8, y, x, y - 8)
        painter.drawLine(x - 12, y, x, y - 12)
        painter.end()


def _create_hover_browser(parent: QWidget) -> HoverTextBrowser:
    """Create a bounded, scrollable hover viewer."""
    browser = HoverTextBrowser(parent)
    browser.setReadOnly(True)
    browser.setUndoRedoEnabled(False)
    browser.setFrameShape(QFrame.Shape.NoFrame)
    browser.setOpenLinks(False)
    browser.setOpenExternalLinks(False)
    browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    browser.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    browser.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    browser.document().setDocumentMargin(0)
    browser.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    browser.resize_finished.connect(_save_hover_size)
    return browser


def _prepare_hover_label(label: QWidget, text: str, note_format: str = "auto"):
    """Size a hover viewer inside the page and render Markdown notes as rich text."""
    parent = label.parentWidget()
    available_width = parent.width() - (_HOVER_LABEL_MARGIN * 2) if parent else 0
    page_max_width = max(40, available_width) if available_width > 0 else _HOVER_LABEL_MAX_WIDTH
    max_width = min(_HOVER_LABEL_MAX_WIDTH, page_max_width)

    rendered_text, text_format = _render_hover_text(text, note_format)

    # Keep short notes compact while capping long notes at max_width.
    longest_line = max(
        (label.fontMetrics().horizontalAdvance(line) for line in text.splitlines()),
        default=0,
    )
    content_width = longest_line + 22  # stylesheet padding plus border
    width = min(max_width, max(min(160, max_width), content_width))

    if isinstance(label, HoverTextBrowser):
        if text_format == Qt.TextFormat.RichText:
            label.setHtml(rendered_text)
        else:
            label.setPlainText(text)
        saved_size = _load_hover_size()
        if getattr(label, "_user_resized", False):
            width = label.width()
            requested_height = label.height()
        elif saved_size is not None:
            width = saved_size.width()
            requested_height = saved_size.height()
        else:
            requested_height = None

        min_width = min(_HOVER_LABEL_MIN_WIDTH, max_width)
        if getattr(label, "_user_resized", False) or saved_size is not None:
            width = max(min_width, min(page_max_width, width))
        else:
            width = max(min_width, min(max_width, width))
        label.setMinimumWidth(min_width)
        label.setMaximumWidth(page_max_width)
        label.resize(width, max(label.height(), _HOVER_LABEL_MIN_HEIGHT))
        # Tell Qt the available line width before measuring the document. The
        # resulting height is bounded, so long answers become scrollable.
        label.document().setTextWidth(max(1, width - 22))
        document_height = label.document().documentLayout().documentSize().height()
        available_height = parent.height() - (_HOVER_LABEL_MARGIN * 2) if parent else 0
        page_max_height = max(40, available_height) if available_height > 0 else _HOVER_LABEL_MAX_HEIGHT
        max_height = min(_HOVER_LABEL_MAX_HEIGHT, page_max_height)
        if requested_height is None:
            requested_height = math.ceil(document_height + 18)
        min_height = min(_HOVER_LABEL_MIN_HEIGHT, max_height)
        if getattr(label, "_user_resized", False) or saved_size is not None:
            height = max(min_height, min(page_max_height, int(requested_height)))
        else:
            height = max(min_height, min(max_height, int(requested_height)))
        label.setMinimumHeight(min_height)
        label.setMaximumHeight(page_max_height)
        label.resize(width, height)
    else:
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setMaximumWidth(max_width)
        label.setTextFormat(text_format)
        label.setText(rendered_text)
        label.setOpenExternalLinks(False)
        label.setFixedWidth(width)
        label.adjustSize()


def _position_hover_label(anchor: QWidget, label: QWidget, offset: QPoint):
    """Place a hover label beside its anchor without leaving the page overlay."""
    parent = anchor.parentWidget()
    if parent is None:
        return

    anchor_pos = anchor.mapTo(parent, QPoint(0, 0))
    x = anchor_pos.x() + offset.x()
    y = anchor_pos.y() + offset.y()
    margin = _HOVER_LABEL_MARGIN

    # Prefer the requested side, then flip horizontally/vertically if needed.
    if x + label.width() > parent.width() - margin:
        x = anchor_pos.x() - label.width() - margin
    if y + label.height() > parent.height() - margin:
        y = anchor_pos.y() - label.height() - margin

    x = max(margin, min(x, max(margin, parent.width() - label.width() - margin)))
    y = max(margin, min(y, max(margin, parent.height() - label.height() - margin)))
    label.move(x, y)


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
            # Selection highlight is rendered by SelectionStripWidget so the
            # text underneath stays fully readable. Keep WordWidget itself
            # visually transparent.
            painter.fillRect(self.rect(), QColor(255, 255, 255, 1))
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


class AnnotationIconWidget(QWidget):
    """
    Small icon placed on PDF page for annotations.
    Double-click to edit, hover to view, drag to move, right-click for menu.
    """
    edit_requested = Signal(int, object)       # annotation_id, global_pos
    hover_entered = Signal(int, str, object)   # annotation_id, text, global_pos
    hover_left = Signal(int)                    # annotation_id
    delete_requested = Signal(int)              # annotation_id
    moved = Signal(int, float, float)           # annotation_id, new_pdf_x, new_pdf_y
    drag_started = Signal(object)                # global QPoint
    drag_moved = Signal(object)                 # global QPoint
    drag_finished = Signal(object)              # global QPoint

    def __init__(self, annotation_id: int, x: float, y: float, width: float = 24, height: float = 24, note_text: str = "", note_format: str = "auto", unzoomed_pos: tuple = None, parent=None):
        super().__init__(parent)
        self.annotation_id = annotation_id
        self.note_text = note_text
        self.note_format = note_format or "auto"
        self.unzoomed_pos = unzoomed_pos or (x, y)  # (x, y) in PDF coordinates
        self.setGeometry(int(x), int(y), int(width), int(height))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._drag_start = None
        self._drag_offset = None
        self._dragging = False
        self._hover_pinned = False
        # Floating label for hover display (child widget, not a separate window)
        self._hover_label = None

    def update_geometry(self, x: float, y: float, width: float, height: float):
        self.setGeometry(int(x), int(y), int(width), int(height))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Draw a small circle with a pen icon
        painter.setBrush(QColor(255, 193, 7, 220))
        painter.setPen(QPen(QColor(200, 150, 0), 1))
        painter.drawEllipse(2, 2, self.width() - 4, self.height() - 4)
        # Draw pen symbol
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        font = painter.font()
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "✎")
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.raise_()
            self._drag_start = event.globalPosition().toPoint()
            self._drag_offset = event.position().toPoint()
            self._dragging = False
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            current = event.globalPosition().toPoint()
            delta = current - self._drag_start
            if not self._dragging and (abs(delta.x()) > 5 or abs(delta.y()) > 5):
                self._dragging = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self._hide_hover_label(force=True)
                self.drag_started.emit(current)
            if self._dragging:
                self.drag_moved.emit(current)
                self._drag_start = current
                event.accept()
                return

        # Keep the hover hint next to the icon while the cursor moves over it.
        if self._hover_label is not None and self._hover_label.isVisible():
            _position_hover_label(self, self._hover_label, QPoint(28, 0))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start is not None:
            was_dragging = self._dragging
            global_pos = event.globalPosition().toPoint()
            self._dragging = False
            self._drag_start = None
            self._drag_offset = None
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            if was_dragging:
                self.drag_finished.emit(global_pos)
            else:
                self._toggle_hover_pin()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _show_context_menu(self, global_pos):
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
        act_edit = menu.addAction("✏️ Edit Annotation")
        act_edit.triggered.connect(lambda: self.edit_requested.emit(self.annotation_id, global_pos))
        act_delete = menu.addAction("🗑️ Delete Annotation")
        act_delete.triggered.connect(lambda: self.delete_requested.emit(self.annotation_id))
        menu.exec(global_pos)

    def _get_page_view(self):
        parent = self.parent()
        while parent:
            if isinstance(parent, PageView):
                return parent
            parent = parent.parent()
        return None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # A double-click is reserved for editing, so do not leave the
            # hover viewer pinned after the edit gesture completes.
            self._hide_hover_label(force=True)
            self.edit_requested.emit(self.annotation_id, event.globalPosition().toPoint())
            event.accept()

    def _ensure_hover_label(self):
        if self._hover_label is None:
            self._hover_label = _create_hover_browser(self.parentWidget())
            self._hover_label.setStyleSheet(_get_hover_label_style())
        return self._hover_label

    def _show_hover_label(self):
        label = self._ensure_hover_label()
        display = self.note_text if self.note_text else "(Double-click to add note)"
        _prepare_hover_label(label, display, self.note_format)
        _position_hover_label(self, label, QPoint(28, 0))
        label.show()
        label.raise_()

    def _set_hover_pinned(self, pinned: bool):
        self._hover_pinned = pinned
        if self._hover_label is None:
            return
        self._hover_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, not pinned
        )
        self._hover_label.setFocusPolicy(
            Qt.FocusPolicy.StrongFocus if pinned else Qt.FocusPolicy.NoFocus
        )
        if isinstance(self._hover_label, HoverTextBrowser):
            self._hover_label.set_resize_enabled(pinned)

    def _toggle_hover_pin(self):
        if not self.note_text and self._hover_label is None:
            self._show_hover_label()
        self._set_hover_pinned(not self._hover_pinned)
        if self._hover_pinned:
            self._show_hover_label()
            self._hover_label.setFocus()
        else:
            self._hide_hover_label(force=True)
            self.hover_left.emit(self.annotation_id)

    def _hide_hover_label(self, force: bool = False):
        if self._hover_pinned and not force:
            return
        if force:
            self._hover_pinned = False
        if self._hover_label is not None:
            self._hover_label.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            if isinstance(self._hover_label, HoverTextBrowser):
                self._hover_label.set_resize_enabled(False)
            self._hover_label.hide()

    def enterEvent(self, event):
        from PySide6.QtGui import QCursor
        # Create a scrollable child viewer without leaving the page overlay.
        self._show_hover_label()
        self.hover_entered.emit(self.annotation_id, self.note_text, QCursor.pos())
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hide_hover_label()
        if not self._hover_pinned:
            self.hover_left.emit(self.annotation_id)
        super().leaveEvent(event)

class HighlightWidget(QWidget):
    """
    Visual overlay showing a persistent text highlight.
    Receives mouse events for click-to-select, right-click delete/copy,
    and keyboard shortcuts (Ctrl+C).
    """
    highlight_deleted = Signal(int)
    highlight_selected = Signal(int)
    highlight_copied = Signal(str)
    annotation_edit_requested = Signal(int, object)      # highlight_id, global_pos
    annotation_hover_entered = Signal(int, str, object)  # highlight_id, text, global_pos
    annotation_hover_left = Signal(int)                   # highlight_id

    def __init__(self, highlight_id: int, color: str, x: float, y: float, width: float, height: float, text: str = "", line_rects: list = None, unzoomed_rect: tuple = None, parent=None):
        super().__init__(parent)
        self.highlight_id = highlight_id
        self.color = color
        self.text = text
        self.line_rects = line_rects or []  # list of QRect relative to widget top-left
        # Store unzoomed bbox for fast geometry updates on rescale
        self.unzoomed_rect = unzoomed_rect  # (x, y, width, height) in PDF coordinates
        self.annotation_text = ""  # attached annotation note
        self.annotation_format = "auto"
        self.setGeometry(int(x), int(y), int(width) + 1, int(height) + 1)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._hovered = False
        self._selected = False
        self._hover_label = None  # child widget for hover display

    def set_selected(self, selected: bool):
        self._selected = selected
        self.update()

    def update_geometry(self, x: float, y: float, width: float, height: float, line_rects: list = None):
        self.setGeometry(int(x), int(y), int(width) + 1, int(height) + 1)
        if line_rects is not None:
            self.line_rects = line_rects
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

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

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.annotation_edit_requested.emit(self.highlight_id, event.globalPosition().toPoint())
            event.accept()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        if self.annotation_text:
            from PySide6.QtGui import QCursor
            # Create hover label as child widget (no window system delay)
            if self._hover_label is None:
                self._hover_label = _create_hover_browser(self.parentWidget())
                self._hover_label.setStyleSheet(_get_hover_label_style())
            _prepare_hover_label(self._hover_label, self.annotation_text, self.annotation_format)
            _position_hover_label(self, self._hover_label, QPoint(10, -30))
            self._hover_label.show()
            self._hover_label.raise_()
            self.annotation_hover_entered.emit(self.highlight_id, self.annotation_text, QCursor.pos())
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        if self._hover_label is not None:
            self._hover_label.hide()
        self.annotation_hover_left.emit(self.highlight_id)
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        # Update hover label position when cursor moves while hovering
        if self._hover_label is not None and self._hover_label.isVisible():
            _position_hover_label(self, self._hover_label, QPoint(10, -30))
        super().mouseMoveEvent(event)

    def set_annotation_text(self, text: str, note_format: str = "auto"):
        """Set attached annotation text and update visual indicator."""
        self.annotation_text = text
        self.annotation_format = note_format or "auto"
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        rects = self.line_rects if self.line_rects else [self.rect()]

        # Marker-style underline: colour only the bottom part of each line so
        # the text above remains perfectly readable.
        marker = QColor(self.color)
        marker.setAlpha(160 if self._selected else (130 if self._hovered else 100))
        for rect in rects:
            h = max(3, int(rect.height() * 0.35))
            underline = QRect(rect.x(), rect.y() + rect.height() - h, rect.width(), h)
            painter.fillRect(underline, marker)

        # Draw small indicator dot if annotation exists
        if self.annotation_text:
            dot_color = QColor(255, 193, 7, 220)  # Amber
            painter.setBrush(dot_color)
            painter.setPen(QPen(QColor(200, 150, 0), 1))
            first_rect = rects[0]
            dot_x = first_rect.x() + 2
            dot_y = first_rect.y() + 2
            painter.drawEllipse(dot_x, dot_y, 8, 8)

        if self._selected:
            colors = get_theme_colors()
            selected_color = QColor(colors.get("selected", "#3a5a8a"))
            pen = QPen(selected_color)
            pen.setWidth(2)
            pen.setStyle(Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for rect in rects:
                painter.drawRect(rect.adjusted(2, 2, -2, -2))
        elif self._hovered:
            pen = QPen(QColor(255, 255, 255, 180))
            pen.setWidth(1)
            pen.setStyle(Qt.PenStyle.DotLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for rect in rects:
                painter.drawRect(rect.adjusted(1, 1, -1, -1))
        painter.end()


class SearchHighlightWidget(QWidget):
    """
    Temporary visual overlay for Target Reading search results.
    Not persisted to the database; cleared when the mode is exited.
    """

    def __init__(self, x: float, y: float, width: float, height: float, active: bool = False, line_rects: list = None, parent=None):
        super().__init__(parent)
        self.line_rects = line_rects or []
        self.setGeometry(int(x), int(y), int(width) + 1, int(height) + 1)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._active = active

    def set_active(self, active: bool):
        self._active = active
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        # Soft yellow marker rendered behind the text overlay, so it can be
        # a bit more saturated without hurting readability.
        fill = QColor(255, 249, 196)
        fill.setAlpha(120 if self._active else 80)

        rects = self.line_rects if self.line_rects else [self.rect()]
        for rect in rects:
            painter.fillRect(rect, fill)

        # Subtle border only for the active match
        if self._active:
            border = QColor(251, 192, 45)
            pen = QPen(border)
            pen.setWidth(1)
            pen.setStyle(Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for rect in rects:
                painter.drawRect(rect.adjusted(1, 1, -1, -1))
        painter.end()


class SelectionStripWidget(QWidget):
    """
    Temporary line-strip overlay shown while the user is dragging a text selection.
    Gives a standard PDF-reader feel (continuous highlight block instead of per-word boxes).
    """

    def __init__(self, x: float, y: float, width: float, height: float, line_rects: list = None, parent=None):
        super().__init__(parent)
        self.line_rects = line_rects or []
        self.setGeometry(int(x), int(y), int(width) + 1, int(height) + 1)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

    def paintEvent(self, event):
        painter = QPainter(self)
        fill = QColor(100, 181, 246)
        fill.setAlpha(55)
        for rect in self.line_rects:
            painter.fillRect(rect, fill)
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
    annotation_edit_requested = Signal(int, object)      # annotation_id, global_pos
    annotation_hover_entered = Signal(int, str, object)  # annotation_id, text, global_pos
    annotation_hover_left = Signal(int)                   # annotation_id
    annotation_placed = Signal(int, object)              # annotation_id, global_pos
    annotation_drag_started = Signal(object, object)      # widget, global_pos
    annotation_drag_moved = Signal(object, object)        # widget, global_pos
    annotation_drag_finished = Signal(object, object)     # widget, global_pos

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
        self.selection_strip_widgets: list[SelectionStripWidget] = []

        self.image_label = QLabel(self)
        self.image_label.setScaledContents(False)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        # Layer that sits above the rendered page image but below the text overlay.
        # Used for non-interactive search highlights so text remains fully readable.
        self.highlight_layer = QWidget(self)
        self.highlight_layer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.highlight_layer.setStyleSheet("background: transparent;")

        self.overlay = QWidget(self)
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.overlay.setStyleSheet("background: transparent;")
        self.overlay.setMouseTracking(True)  # Enable hover events for children
        # Click on empty area clears selection; double-click on empty area captures whole page
        self.overlay.mousePressEvent = self._on_overlay_press
        self.overlay.mouseMoveEvent = self._on_overlay_move
        self.overlay.mouseReleaseEvent = self._on_overlay_release
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
        self.annotation_mode = False
        self.annotation_widgets: list[AnnotationIconWidget] = []
        self._image_dirty = False

        self.load_page()

    def _on_overlay_press(self, event):
        local_pos = event.pos()
        # Annotation mode: place icon at click position
        if self.annotation_mode:
            self._place_annotation_at(local_pos)
            return
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

    def _place_annotation_at(self, local_pos):
        """Place an annotation icon at the given local position."""
        if not self.engine or not self.engine.path:
            return
        from core import database
        from PySide6.QtGui import QCursor
        # Convert to unzoomed PDF coordinates
        pdf_x = local_pos.x() / self.zoom
        pdf_y = local_pos.y() / self.zoom
        annot_id = database.add_annotation(
            self.engine.path, self.page_number,
            pdf_x, pdf_y, "", "icon", 0, 24, 24
        )
        self._create_annotation_widget(annot_id, pdf_x, pdf_y, "", "auto")
        # Exit annotation mode after placing
        self.annotation_mode = False
        self.unsetCursor()
        # Notify main window to auto-open editor
        self.annotation_placed.emit(annot_id, QCursor.pos())

    def _create_annotation_widget(self, annot_id: int, pdf_x: float, pdf_y: float,
                                  note_text: str, note_format: str = "auto"):
        """Create an AnnotationIconWidget from PDF coordinates."""
        widget = AnnotationIconWidget(
            annot_id,
            pdf_x * self.zoom, pdf_y * self.zoom,
            24, 24, note_text, note_format,
            unzoomed_pos=(pdf_x, pdf_y),
            parent=self.overlay
        )
        widget.edit_requested.connect(self._on_annotation_edit_requested)
        widget.hover_entered.connect(self._on_annotation_hover_entered)
        widget.hover_left.connect(self._on_annotation_hover_left)
        widget.delete_requested.connect(self._on_annotation_delete_requested)
        widget.drag_started.connect(self._on_annotation_drag_started)
        widget.drag_moved.connect(self._on_annotation_drag_moved)
        widget.drag_finished.connect(self._on_annotation_drag_finished)
        widget.show()
        widget.raise_()  # Ensure it's on top of overlay children
        self.annotation_widgets.append(widget)
        print(f"[DEBUG] Created annotation widget: id={annot_id}, visible={widget.isVisible()}, pos=({pdf_x},{pdf_y})")
        return widget

    def _on_annotation_delete_requested(self, annot_id: int):
        """Handle annotation icon delete request."""
        from core import database
        database.delete_annotation(annot_id)
        removed = self.remove_annotation_widget(annot_id)
        if not removed:
            scroll_view = self._get_pdf_scroll_view()
            if scroll_view is not None:
                for page_view in scroll_view.page_views:
                    if page_view.remove_annotation_widget(annot_id):
                        break
        self.annotation_hover_left.emit(annot_id)

    def _get_pdf_scroll_view(self):
        parent = self.parent()
        while parent:
            if hasattr(parent, "page_views") and hasattr(parent, "container"):
                return parent
            parent = parent.parent()
        return None

    def _on_annotation_drag_started(self, global_pos):
        self.annotation_drag_started.emit(self.sender(), global_pos)

    def _on_annotation_drag_moved(self, global_pos):
        self.annotation_drag_moved.emit(self.sender(), global_pos)

    def _on_annotation_drag_finished(self, global_pos):
        self.annotation_drag_finished.emit(self.sender(), global_pos)

    def _on_annotation_edit_requested(self, annot_id: int, global_pos):
        """Forward annotation edit request."""
        self.annotation_edit_requested.emit(annot_id, global_pos)

    def _on_annotation_hover_entered(self, annot_id: int, text: str, global_pos):
        self.annotation_hover_entered.emit(annot_id, text, global_pos)

    def _on_annotation_hover_left(self, annot_id: int):
        self.annotation_hover_left.emit(annot_id)

    def load_annotations(self):
        """Load annotations for this page from database."""
        if not self.engine or not self.engine.path:
            return
        from core import database
        annotations = database.get_annotations(self.engine.path, self.page_number)
        print(f"[DEBUG] load_annotations for page {self.page_number}: found {len(annotations)} annotations")
        for annot in annotations:
            if annot["target_type"] == "icon":
                self._create_annotation_widget(
                    annot["id"], annot["x"], annot["y"], annot["note_text"],
                    annot.get("note_format", "auto")
                )

    def update_annotation_geometries(self):
        """Update annotation icon positions after zoom change."""
        for widget in self.annotation_widgets:
            if widget.unzoomed_pos:
                x, y = widget.unzoomed_pos
                widget.update_geometry(x * self.zoom, y * self.zoom, 24, 24)

    def remove_annotation_widget(self, annot_id: int):
        """Remove an annotation widget by id."""
        for widget in self.annotation_widgets[:]:
            if widget.annotation_id == annot_id:
                widget.setParent(None)
                widget.deleteLater()
                self.annotation_widgets.remove(widget)
                return True
        return False

    def set_annotation_mode(self, active: bool):
        """Enter or exit annotation placement mode."""
        self.annotation_mode = active
        if active:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.unsetCursor()

    def _on_overlay_move(self, event):
        # Always check if mouse left annotation widgets (for tooltip hide)
        self._check_tooltip_hide(event.pos())
        
        if not self.selection_active:
            return
        target = self.widget_at_global(event.globalPosition().toPoint())
        if target and isinstance(target, WordWidget):
            self.add_to_selection(target)

    def _check_tooltip_hide(self, local_pos):
        """Hide tooltip if mouse is not over any annotation widget or highlight."""
        # A pinned viewer remains available while the cursor moves from the
        # icon into the viewer (and while the user scrolls inside it).
        for widget in self.annotation_widgets:
            if getattr(widget, "_hover_pinned", False):
                return

        # Check if mouse is over any annotation icon
        for widget in self.annotation_widgets:
            if widget.geometry().contains(local_pos):
                return  # Still over an icon, don't hide

            label = getattr(widget, "_hover_label", None)
            if label is not None and label.isVisible() and label.geometry().contains(local_pos):
                return  # Still over an unpinned viewer during the transition
        
        # Check if mouse is over any highlight with annotation
        for hw in self.highlight_widgets:
            if hw.geometry().contains(local_pos) and hw.annotation_text:
                return  # Still over annotated highlight, don't hide
        
        # Mouse left all annotation targets - hide tooltip immediately
        self._hide_all_tooltips()

    def _hide_all_tooltips(self):
        """Hide all hover labels immediately."""
        for widget in self.annotation_widgets:
            if hasattr(widget, "_hide_hover_label"):
                widget._hide_hover_label()
            elif widget._hover_label is not None:
                widget._hover_label.hide()
        for hw in self.highlight_widgets:
            if hw._hover_label is not None:
                hw._hover_label.hide()

    def _on_overlay_release(self, event):
        if self.selection_active:
            self.finish_selection(event.globalPosition().toPoint())


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
        print(f"[DEBUG] load_page called for page {self.page_number}")
        image = self.engine.render_page(self.page_number, self.zoom)
        if image is None:
            return
        pixmap = QPixmap.fromImage(image)
        self.image_label.setPixmap(pixmap)
        self.image_label.resize(pixmap.width(), pixmap.height())
        self.highlight_layer.setGeometry(0, 0, pixmap.width(), pixmap.height())
        self.overlay.setGeometry(0, 0, pixmap.width(), pixmap.height())
        self.overlay.raise_()
        self.setFixedSize(pixmap.width(), pixmap.height())
        self._build_word_widgets()
        self._build_image_hit_widgets()
        self._build_link_widgets()
        self._load_highlights()
        self.load_annotations()

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
        else:
            self.overlay.raise_()

    def _update_geometry(self):
        """Update sizes based on page rect without rendering."""
        page = self.engine.doc.load_page(self.page_number)
        w = int(page.rect.width * self.zoom)
        h = int(page.rect.height * self.zoom)
        self.image_label.resize(w, h)
        self.highlight_layer.setGeometry(0, 0, w, h)
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
        self._raise_annotation_widgets()

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
        self._raise_annotation_widgets()

    def _update_image_hit_widgets(self):
        """Rebuild image hit widgets after zoom change (simpler than matching by index)."""
        self._build_image_hit_widgets()

    def _raise_annotation_widgets(self):
        """Keep annotation icons above image and link hit areas."""
        for widget in self.annotation_widgets:
            if widget.parentWidget() is self.overlay:
                widget.raise_()

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
        self._update_selection_strips()
        self.overlay.grabMouse()

    def add_to_selection(self, widget: WordWidget):
        if widget not in self.selected_widgets:
            widget.set_selected(True)
            self.selected_widgets.add(widget)
            self._update_selection_preview()
            self._update_selection_strips()

    def _update_selection_strips(self):
        """Render the current text selection as continuous line strips."""
        for w in self.selection_strip_widgets:
            w.setParent(None)
            w.deleteLater()
        self.selection_strip_widgets.clear()

        if not self.selected_widgets:
            return

        sorted_widgets = sorted(self.selected_widgets, key=lambda w: (w.y(), w.x()))
        x0, y0, x1, y1, line_rects = self._build_line_strips(sorted_widgets)
        sw = SelectionStripWidget(x0, y0, x1 - x0, y1 - y0, line_rects=line_rects, parent=self.overlay)
        sw.show()
        self.selection_strip_widgets.append(sw)

    def finish_selection(self, global_pos):
        self.selection_active = False
        try:
            self.overlay.releaseMouse()
        except Exception:
            pass
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

    def _build_line_strips(self, words: list[WordWidget]) -> tuple[float, float, float, float, list]:
        """
        Group words by (block, line) and build continuous line-strip bboxes.
        Returns (x0, y0, x1, y1, line_rects) where line_rects are QRects
        relative to the overall top-left corner (x0, y0).
        """
        if not words:
            return 0, 0, 0, 0, []

        # Group by line, preserving reading order
        groups: dict[tuple[int, int], list[WordWidget]] = {}
        order: list[tuple[int, int]] = []
        for w in words:
            key = (w.block, w.line)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(w)

        line_rects = []
        x0 = min(w.x() for w in words)
        y0 = min(w.y() for w in words)
        x1 = max(w.x() + w.width() for w in words)
        y1 = max(w.y() + w.height() for w in words)

        for key in order:
            group = groups[key]
            gx0 = min(w.x() for w in group)
            gy0 = min(w.y() for w in group)
            gx1 = max(w.x() + w.width() for w in group)
            gy1 = max(w.y() + w.height() for w in group)
            # Relative to overall bbox
            line_rects.append(QRect(int(gx0 - x0), int(gy0 - y0), int(gx1 - gx0) + 1, int(gy1 - gy0) + 1))

        return x0, y0, x1, y1, line_rects

    def _apply_highlight(self, color: str):
        if not self.selected_widgets or not self.engine or not self.engine.path:
            return
        sorted_widgets = sorted(self.selected_widgets, key=lambda w: (w.y(), w.x()))
        if not sorted_widgets:
            return
        x0, y0, x1, y1, line_rects = self._build_line_strips(sorted_widgets)
        texts = " ".join(w.text for w in sorted_widgets)
        # Save overall bbox to DB
        from core import database
        hid = database.save_highlight(
            self.engine.path, self.page_number, texts,
            x0 / self.zoom, y0 / self.zoom, (x1 - x0) / self.zoom, (y1 - y0) / self.zoom,
            color
        )
        # Create line-strip widget
        hw = HighlightWidget(
            hid, color, x0, y0, x1 - x0, y1 - y0,
            text=texts, line_rects=line_rects, parent=self.overlay
        )
        hw.highlight_deleted.connect(self._on_highlight_deleted)
        hw.highlight_selected.connect(self._on_highlight_selected)
        hw.annotation_edit_requested.connect(self._on_hw_annotation_edit)
        hw.annotation_hover_entered.connect(self._on_hw_annotation_hover)
        hw.annotation_hover_left.connect(self._on_hw_annotation_leave)
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
        for w in self.selection_strip_widgets:
            w.setParent(None)
            w.deleteLater()
        self.selection_strip_widgets.clear()
        try:
            self.overlay.releaseMouse()
        except Exception:
            pass

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
        """Load persistent highlights from DB for this page as line strips."""
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
            ux, uy, uw, uh = h["x"], h["y"], h["width"], h["height"]
            x0, y0, w0, h0 = ux * self.zoom, uy * self.zoom, uw * self.zoom, uh * self.zoom
            words = self._words_in_rect(x0, y0, w0, h0)
            _, _, _, _, line_rects = self._build_line_strips(words) if words else (x0, y0, x0 + w0, y0 + h0, [QRect(0, 0, int(w0) + 1, int(h0) + 1)])
            hw = HighlightWidget(
                highlight_id=h["id"],
                color=h["color"],
                x=x0,
                y=y0,
                width=w0,
                height=h0,
                text=h.get("text", ""),
                line_rects=line_rects,
                unzoomed_rect=(ux, uy, uw, uh),
                parent=self.overlay,
            )
            hw.highlight_deleted.connect(self._on_highlight_deleted)
            hw.highlight_selected.connect(self._on_highlight_selected)
            # Forward annotation signals to PageView level
            hw.annotation_edit_requested.connect(self._on_hw_annotation_edit)
            hw.annotation_hover_entered.connect(self._on_hw_annotation_hover)
            hw.annotation_hover_left.connect(self._on_hw_annotation_leave)
            # Load annotation for this highlight if exists
            annot = database.get_annotation_for_target(self.engine.path, "highlight", h["id"])
            if annot:
                hw.set_annotation_text(
                    annot["note_text"], annot.get("note_format", "auto")
                )
            hw.show()
            self.highlight_widgets.append(hw)

    def _on_hw_annotation_edit(self, highlight_id: int, global_pos):
        """Forward highlight annotation edit: find/create annotation for this highlight."""
        if not self.engine or not self.engine.path:
            return
        from core import database
        annot = database.get_annotation_for_target(self.engine.path, "highlight", highlight_id)
        if annot:
            self.annotation_edit_requested.emit(annot["id"], global_pos)
        else:
            # Create new annotation for this highlight
            annot_id = database.add_annotation(
                self.engine.path, self.page_number, 0, 0, "", "highlight", highlight_id
            )
            self.annotation_edit_requested.emit(annot_id, global_pos)

    def _on_hw_annotation_hover(self, highlight_id: int, text: str, global_pos):
        """Forward highlight annotation hover to PageView signal."""
        self.annotation_hover_entered.emit(highlight_id, text, global_pos)

    def _on_hw_annotation_leave(self, highlight_id: int):
        """Forward highlight annotation leave to PageView signal."""
        self.annotation_hover_left.emit(highlight_id)

    def _words_in_rect(self, x: float, y: float, width: float, height: float) -> list[WordWidget]:
        """Return word widgets whose geometry intersects the given rect."""
        rect = QRect(int(x), int(y), int(width) + 1, int(height) + 1)
        result = []
        for w in self.word_widgets:
            if rect.intersects(w.geometry()):
                result.append(w)
        return result

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
        """Update highlight widget geometries after zoom change without full rebuild."""
        if not self.engine or not self.engine.path:
            return
        # If counts mismatch (e.g. words not rebuilt yet), fall back to full load
        if not self.word_widgets:
            self._load_highlights()
            return

        to_remove = []
        for hw in self.highlight_widgets:
            if hw.unzoomed_rect is None:
                to_remove.append(hw)
                continue
            ux, uy, uw, uh = hw.unzoomed_rect
            x0, y0, w0, h0 = ux * self.zoom, uy * self.zoom, uw * self.zoom, uh * self.zoom
            words = self._words_in_rect(x0, y0, w0, h0)
            _, _, _, _, line_rects = self._build_line_strips(words) if words else (x0, y0, x0 + w0, y0 + h0, [QRect(0, 0, int(w0) + 1, int(h0) + 1)])
            hw.update_geometry(x0, y0, w0, h0, line_rects)

        for hw in to_remove:
            hw.setParent(None)
            hw.deleteLater()
            self.highlight_widgets.remove(hw)

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
        Highlight the first occurrence of *quote* on this page as line strips.
        Returns True if a match was found and highlighted.
        """
        if not self.word_widgets or not quote:
            return False
        quote = quote.strip()
        texts = [w.text for w in self.word_widgets]
        n = len(self.word_widgets)

        # Find the shortest contiguous word window that contains the quote.
        best_start = -1
        best_end = -1
        best_len = float('inf')
        for i in range(n):
            snippet = ""
            for j in range(i, min(n, i + 200)):
                snippet += (" " if snippet else "") + texts[j]
                if quote in snippet:
                    window_len = j - i + 1
                    if window_len < best_len:
                        best_len = window_len
                        best_start = i
                        best_end = j + 1
                    break

        if best_start >= 0:
            matched_widgets = self.word_widgets[best_start:best_end]
        else:
            # Fallback: find any words that appear in the quote and are close together.
            quote_lower = quote.lower()
            candidate_indices = [idx for idx, t in enumerate(texts) if t.lower() in quote_lower]
            if not candidate_indices:
                return False
            # Take the first cluster of candidates within a 40-word window.
            cluster_start = candidate_indices[0]
            cluster_end = cluster_start + 1
            for idx in candidate_indices[1:]:
                if idx <= cluster_start + 40:
                    cluster_end = idx + 1
                else:
                    break
            matched_widgets = self.word_widgets[cluster_start:cluster_end]

        if not matched_widgets:
            return False

        x0, y0, x1, y1, line_rects = self._build_line_strips(matched_widgets)
        w = SearchHighlightWidget(
            x0, y0, x1 - x0, y1 - y0,
            active=active, line_rects=line_rects, parent=self.highlight_layer
        )
        w.show()
        self.search_highlight_widgets.append(w)
        return True

    def set_active_search_highlight(self, active_widget: SearchHighlightWidget | None):
        """Mark one search highlight as active and others inactive."""
        for w in self.search_highlight_widgets:
            w.set_active(w is active_widget)
