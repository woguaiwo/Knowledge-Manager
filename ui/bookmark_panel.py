"""
Bookmark panel with tree structure, drag-and-drop reordering, and import/export.
"""
import json
import os
import re
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal, QMimeData, QByteArray, QEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QInputDialog, QMessageBox, QFileDialog,
    QAbstractItemView, QMenu, QApplication
)
from PySide6.QtGui import QDrag

from core import database
from core.theme_colors import get_theme_colors


class BookmarkTreeWidget(QTreeWidget):
    """Tree widget that supports drag-and-drop reordering and emits signals."""

    structure_changed = Signal()
    bookmark_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.itemDoubleClicked.connect(self._on_double_clicked)
        self.itemClicked.connect(self._on_item_clicked)

        self._current_pdf = ""
        self._current_page = 0

    def set_pdf(self, pdf_path: str):
        """Load bookmarks for the given PDF."""
        self._current_pdf = pdf_path
        self.clear()
        if not pdf_path:
            return
        bookmarks = database.get_bookmarks(pdf_path)
        self._build_tree(bookmarks)

    def _build_tree(self, bookmarks: List[Dict]):
        """Build tree from flat bookmark list."""
        # Group by parent_id
        by_parent: Dict[int, List[Dict]] = {}
        for bm in bookmarks:
            pid = bm["parent_id"]
            if pid not in by_parent:
                by_parent[pid] = []
            by_parent[pid].append(bm)

        # Sort each group by sort_order
        for pid in by_parent:
            by_parent[pid].sort(key=lambda x: x["sort_order"])

        # Recursive build
        def _add_items(parent_item, parent_id):
            for bm in by_parent.get(parent_id, []):
                item = QTreeWidgetItem(parent_item)
                entry_type = bm.get("entry_type", "bookmark")
                if entry_type == "keyword":
                    item.setText(0, f"🏷️ {bm['title']}")
                else:
                    item.setText(0, f"📄 {bm['title']} (p.{bm['page_number'] + 1})")
                item.setData(0, Qt.ItemDataRole.UserRole, bm)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                _add_items(item, bm["id"])

        # Add root items
        root = self.invisibleRootItem()
        _add_items(root, 0)
        self.expandAll()

    def _on_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Start editing on double-click."""
        self.editItem(item, column)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Emit bookmark_clicked when a bookmark (not keyword) is clicked."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("entry_type", "bookmark") == "bookmark":
            self.bookmark_clicked.emit(data["page_number"])

    def keyPressEvent(self, event):
        """Use Enter as a shortcut for adding a child bookmark.

        The selected tree item is the parent.  The child page is taken from
        the PDF page currently selected in the reader.
        """
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
            and self.state() != QAbstractItemView.State.EditingState
        ):
            item = self.currentItem()
            if item is not None:
                self._add_child_item(item, "bookmark")
                event.accept()
                return
        super().keyPressEvent(event)

    def set_current_page(self, page_number: int):
        """Store the PDF page that new child bookmarks should use."""
        try:
            self._current_page = max(0, int(page_number))
        except (TypeError, ValueError):
            self._current_page = 0

    def _show_context_menu(self, pos):
        """Show right-click context menu."""
        item = self.itemAt(pos)
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

        if item:
            # A context-menu invocation should also make the clicked item the
            # active selection, so a subsequent Enter has the same parent.
            self.setCurrentItem(item)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            entry_type = data.get("entry_type", "bookmark")
            act_rename = menu.addAction("✏️ Rename")
            act_rename.triggered.connect(lambda: self._rename_item(item))
            act_delete = menu.addAction("🗑 Delete")
            act_delete.triggered.connect(lambda: self._delete_item(item))
            menu.addSeparator()
            act_add_child = menu.addAction("➕ Add Child Bookmark")
            act_add_child.triggered.connect(lambda: self._add_child_item(item, "bookmark"))
            act_add_keyword = menu.addAction("🏷️ Add Keyword")
            act_add_keyword.triggered.connect(lambda: self._add_child_item(item, "keyword"))
            menu.addSeparator()
            act_move_up = menu.addAction("⬆ Move Up")
            act_move_up.triggered.connect(lambda: self._move_item(item, -1))
            act_move_down = menu.addAction("⬇ Move Down")
            act_move_down.triggered.connect(lambda: self._move_item(item, 1))
        else:
            act_add_root = menu.addAction("➕ Add Root Bookmark")
            act_add_root.triggered.connect(lambda: self._add_root_item("bookmark"))
            act_add_root_keyword = menu.addAction("🏷️ Add Root Keyword")
            act_add_root_keyword.triggered.connect(lambda: self._add_root_item("keyword"))

        menu.exec(self.viewport().mapToGlobal(pos))

    def _rename_item(self, item: QTreeWidgetItem):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        new_title, ok = QInputDialog.getText(
            self, "Rename Bookmark", "New title:", text=data["title"]
        )
        if ok and new_title.strip():
            database.update_bookmark(data["id"], title=new_title.strip())
            data["title"] = new_title.strip()
            item.setText(0, f"📄 {data['title']} (p.{data['page_number'] + 1})")
            item.setData(0, Qt.ItemDataRole.UserRole, data)

    def _delete_item(self, item: QTreeWidgetItem):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "Delete Bookmark",
            f"Delete '{data['title']}' and all its children?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            database.delete_bookmark(data["id"])
            self.set_pdf(self._current_pdf)  # Reload
            self.structure_changed.emit()

    def _add_child_item(self, item: QTreeWidgetItem, entry_type: str = "bookmark"):
        """Add a child bookmark or keyword under the selected item."""
        parent_data = item.data(0, Qt.ItemDataRole.UserRole)
        dialog_title = "Add Child Keyword" if entry_type == "keyword" else "Add Child Bookmark"
        label = "Keyword text:" if entry_type == "keyword" else "Bookmark title:"
        title, ok = QInputDialog.getText(self, dialog_title, label)
        if ok and title.strip():
            # Use the page currently selected in the reader.  The old
            # placeholder value (0) made every child point to page 1.
            page_number = self._current_page if entry_type == "bookmark" else 0
            database.add_bookmark(
                self._current_pdf,
                page_number,
                title.strip(),
                parent_id=parent_data["id"],
                entry_type=entry_type
            )
            self.set_pdf(self._current_pdf)
            self.structure_changed.emit()

    def _add_root_item(self, entry_type: str = "bookmark"):
        """Add a root-level bookmark or keyword."""
        dialog_title = "Add Keyword" if entry_type == "keyword" else "Add Bookmark"
        label = "Keyword text:" if entry_type == "keyword" else "Bookmark title:"
        title, ok = QInputDialog.getText(self, dialog_title, label)
        if ok and title.strip():
            database.add_bookmark(
                self._current_pdf,
                0,  # page_number placeholder
                title.strip(),
                parent_id=0,
                entry_type=entry_type
            )
            self.set_pdf(self._current_pdf)
            self.structure_changed.emit()

    def _move_item(self, item: QTreeWidgetItem, direction: int):
        """Move item up (-1) or down (1) among siblings."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        database.reorder_bookmarks(data["id"], direction)
        self.set_pdf(self._current_pdf)
        self.structure_changed.emit()

    def dropEvent(self, event):
        """Handle drop events for drag-and-drop reordering."""
        super().dropEvent(event)
        # After Qt handles the drop, save the new structure
        self._save_structure()
        self.structure_changed.emit()

    def _save_structure(self):
        """Save current tree structure to database."""
        def _save_item(item: QTreeWidgetItem, parent_id: int, order: int):
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data:
                database.update_bookmark(
                    data["id"],
                    parent_id=parent_id,
                    sort_order=order
                )
            for i in range(item.childCount()):
                _save_item(item.child(i), data["id"] if data else 0, i)

        root = self.invisibleRootItem()
        for i in range(root.childCount()):
            _save_item(root.child(i), 0, i)

    def add_bookmark_for_page(self, page_number: int, title: str, parent_id: int = 0, entry_type: str = "bookmark"):
        """Add a bookmark for a specific page."""
        database.add_bookmark(self._current_pdf, page_number, title, parent_id, entry_type)
        self.set_pdf(self._current_pdf)
        self.structure_changed.emit()


class BookmarkPanel(QWidget):
    """Left panel for managing PDF bookmarks."""

    # Aliases accepted from AI-generated JSON. Exported files continue to use
    # the canonical ``bookmarks`` / ``page_number`` fields.
    _ITEM_LIST_KEYS = ("bookmarks", "items", "outline", "chapters", "sections", "entries", "slides")
    _TITLE_KEYS = ("title", "name", "label", "heading", "text")
    _PAGE_KEYS = ("page_number", "page", "slide_number", "slide", "page_no", "slide_no")
    _CHILDREN_KEYS = ("children", "bookmarks", "items", "subsections", "subtopics", "sections")

    bookmark_clicked = Signal(int)
    add_current_page_requested = Signal()
    structure_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_pdf = ""
        self._current_page = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Header
        header = QLabel("🔖 Bookmarks")
        header.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(header)

        # Add current page button
        self.btn_add = QPushButton("➕ Add Current Page")
        self.btn_add.clicked.connect(self._on_add_current_page)
        layout.addWidget(self.btn_add)

        # Tree widget
        self.tree = BookmarkTreeWidget()
        self.tree.bookmark_clicked.connect(self.bookmark_clicked.emit)
        self.tree.structure_changed.connect(self.structure_changed.emit)
        # External JSON drops should be handled by the importer while the
        # tree keeps its internal drag-and-drop reordering.
        self.tree.viewport().installEventFilter(self)
        layout.addWidget(self.tree)

        # Export / Import buttons
        btn_layout = QHBoxLayout()
        self.btn_export = QPushButton("📤 Export")
        self.btn_export.clicked.connect(self._on_export)
        self.btn_import = QPushButton("📥 Import")
        self.btn_import.clicked.connect(lambda: self._on_import())
        btn_layout.addWidget(self.btn_export)
        btn_layout.addWidget(self.btn_import)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        layout.addStretch()
        self.setAcceptDrops(True)

    @staticmethod
    def _json_drop_paths(mime_data) -> List[str]:
        """Return local JSON paths from a drag/drop mime payload."""
        if not mime_data or not mime_data.hasUrls():
            return []
        paths = []
        for url in mime_data.urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                if path.lower().endswith(".json"):
                    paths.append(path)
        return paths

    def dragEnterEvent(self, event):
        if self._json_drop_paths(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event):
        paths = self._json_drop_paths(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self._import_from_path(paths[0])
            return
        super().dropEvent(event)

    def eventFilter(self, watched, event):
        """Intercept external JSON drops over the tree viewport."""
        if watched is self.tree.viewport():
            if event.type() == QEvent.Type.DragEnter:
                if self._json_drop_paths(event.mimeData()):
                    event.acceptProposedAction()
                    return True
            elif event.type() == QEvent.Type.Drop:
                paths = self._json_drop_paths(event.mimeData())
                if paths:
                    event.acceptProposedAction()
                    self._import_from_path(paths[0])
                    return True
        return super().eventFilter(watched, event)

    def set_pdf(self, pdf_path: str):
        """Set the current PDF and reload bookmarks."""
        self._current_pdf = pdf_path
        self.tree.set_pdf(pdf_path)

    def set_current_page(self, page_number: int):
        """Update the current page number for 'Add Current Page' button."""
        try:
            self._current_page = max(0, int(page_number))
        except (TypeError, ValueError):
            self._current_page = 0
        self.tree.set_current_page(self._current_page)

    def _on_add_current_page(self):
        """Request to add a bookmark for the current page."""
        if not self._current_pdf:
            QMessageBox.warning(self, "No PDF", "Please open a PDF first.")
            return
        title, ok = QInputDialog.getText(
            self, "Add Bookmark", "Bookmark title:",
            text=f"Page {self._current_page + 1}"
        )
        if ok and title.strip():
            self.tree.add_bookmark_for_page(self._current_page, title.strip())

    def _on_export(self):
        """Export bookmarks to a JSON file."""
        if not self._current_pdf:
            QMessageBox.warning(self, "No PDF", "Please open a PDF first.")
            return

        bookmarks = database.get_bookmarks(self._current_pdf)
        if not bookmarks:
            QMessageBox.information(self, "No Bookmarks", "No bookmarks to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Bookmarks",
            f"{os.path.basename(self._current_pdf)}.bookmarks.json",
            "JSON Files (*.json)"
        )
        if not path:
            return

        # Build nested structure
        def _build_tree(parent_id: int) -> List[Dict]:
            result = []
            children = [b for b in bookmarks if b["parent_id"] == parent_id]
            children.sort(key=lambda x: x["sort_order"])
            for child in children:
                result.append({
                    "title": child["title"],
                    "page_number": child["page_number"],
                    "entry_type": child.get("entry_type", "bookmark"),
                    "children": _build_tree(child["id"])
                })
            return result

        tree_data = _build_tree(0)
        export_data = {
            "format": "knowledge-manager-bookmarks",
            "version": 1,
            # Database page_number values are zero-based. Keeping this explicit
            # makes exported files unambiguous and gives AI output a clear
            # counterpart (page_number_base: 1).
            "page_number_base": 0,
            "pdf_path": self._current_pdf,
            "exported_at": __import__("datetime").datetime.now().isoformat(),
            "bookmarks": tree_data
        }

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "Export", f"Bookmarks exported to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export:\n{e}")

    @staticmethod
    def _strip_json_code_fence(text: str) -> str:
        """Remove a Markdown JSON fence commonly added by chat models."""
        text = text.lstrip("\ufeff").strip()
        if not text.startswith("```"):
            return text
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()

    @classmethod
    def _page_base(cls, data: Dict) -> tuple[int, bool]:
        """Read an explicit page numbering base from document metadata."""
        value = data.get("page_number_base", data.get("page_base"))
        if value is None:
            value = data.get("numbering")
        if isinstance(value, str):
            normalized = value.strip().lower().replace("_", "-")
            if normalized in {"1", "1-based", "one-based", "one"}:
                return 1, True
            if normalized in {"0", "0-based", "zero-based", "zero"}:
                return 0, True
        elif value in (0, 1):
            return int(value), True
        return 0, False

    @staticmethod
    def _coerce_page(value, default: int) -> int:
        """Convert an AI-produced page/slide value into an integer."""
        if value is None or isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        text = str(value).strip()
        try:
            return int(text)
        except ValueError:
            # Also accept values such as "Slide 12" or "第12页".
            match = re.search(r"\d+", text)
            return int(match.group()) if match else default

    @classmethod
    def _extract_import_items(cls, data):
        """Extract the item list from supported AI/export root shapes."""
        if isinstance(data, list):
            return data, {}, False
        if not isinstance(data, dict):
            raise ValueError("JSON root must be an object or an array.")

        for key in cls._ITEM_LIST_KEYS:
            value = data.get(key)
            if isinstance(value, list):
                return value, data, True

        # A single bookmark object is convenient for small AI outputs.
        if any(key in data for key in cls._TITLE_KEYS) or "children" in data:
            return [data], data, True
        keys = ", ".join(cls._ITEM_LIST_KEYS)
        raise ValueError(f"No bookmark list found. Expected one of: {keys}.")

    @classmethod
    def _normalize_import_items(cls, items, metadata):
        """Normalize common AI fields to the database representation."""
        page_base, explicit_base = cls._page_base(metadata)
        warnings = []
        normalized_count = 0

        def normalize(node, path: str):
            nonlocal normalized_count
            if not isinstance(node, dict):
                warnings.append(f"{path}: item is not an object and was skipped")
                return None

            title = ""
            for key in cls._TITLE_KEYS:
                if node.get(key) is not None:
                    title = str(node[key]).strip()
                    if title:
                        break
            if not title:
                title = "Untitled"
                warnings.append(f"{path}: missing title, using 'Untitled'")

            page_key = next((key for key in cls._PAGE_KEYS if key in node), None)
            raw_page = node.get(page_key) if page_key else 0
            # "page" and "slide" are natural-language fields and are treated
            # as one-based when no explicit metadata says otherwise. The
            # exported page_number field keeps its historical zero-based rule.
            item_base = page_base
            if not explicit_base and page_key in {"page", "slide_number", "slide", "page_no", "slide_no"}:
                item_base = 1
            page = cls._coerce_page(raw_page, 0)
            page = max(0, page - item_base)

            entry_type = str(node.get("entry_type", node.get("type", "bookmark"))).strip().lower()
            if entry_type not in {"bookmark", "keyword"}:
                warnings.append(f"{path}: unknown entry_type '{entry_type}', using 'bookmark'")
                entry_type = "bookmark"

            children = []
            child_key = next(
                (key for key in cls._CHILDREN_KEYS if isinstance(node.get(key), (list, dict))),
                None,
            )
            if child_key:
                raw_children = node[child_key]
                if isinstance(raw_children, dict):
                    raw_children = [raw_children]
                for index, child in enumerate(raw_children):
                    normalized_child = normalize(child, f"{path}.children[{index}]")
                    if normalized_child is not None:
                        children.append(normalized_child)

            normalized_count += 1
            return {
                "title": title,
                "page_number": page,
                "entry_type": entry_type,
                "children": children,
            }

        result = []
        for index, item in enumerate(items):
            normalized = normalize(item, f"bookmarks[{index}]")
            if normalized is not None:
                result.append(normalized)
        return result, warnings, normalized_count

    def _read_import_file(self, path: str):
        """Read and normalize an exported or AI-generated JSON file."""
        with open(path, "r", encoding="utf-8-sig") as f:
            raw_text = self._strip_json_code_fence(f.read())
        data = json.loads(raw_text)
        items, metadata, _ = self._extract_import_items(data)
        normalized, warnings, count = self._normalize_import_items(items, metadata)
        if not normalized:
            raise ValueError("The JSON file contains no usable bookmarks.")
        return normalized, warnings, count

    def _import_from_path(self, path: str):
        """Import one JSON file, replacing the current PDF's bookmark tree."""
        if not self._current_pdf:
            QMessageBox.warning(self, "No PDF", "Please open a PDF first.")
            return False

        try:
            bookmarks, warnings, count = self._read_import_file(path)
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to read bookmark JSON:\n{e}")
            return False

        # Never erase an existing outline without an explicit confirmation.
        existing = database.get_bookmarks(self._current_pdf)
        if existing:
            reply = QMessageBox.question(
                self,
                "Replace Bookmarks",
                f"This PDF already has {len(existing)} bookmark entries.\n"
                "Replace them with the imported outline?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False

        for bm in existing:
            database.delete_bookmark(bm["id"])

        def _import_tree(items: List[Dict], parent_id: int = 0):
            for item in items:
                new_id = database.add_bookmark(
                    self._current_pdf,
                    item["page_number"],
                    item["title"],
                    parent_id,
                    item["entry_type"],
                )
                if item["children"]:
                    _import_tree(item["children"], new_id)

        _import_tree(bookmarks)
        self.tree.set_pdf(self._current_pdf)
        self.structure_changed.emit()
        message = f"Imported {count} bookmark entries successfully."
        if warnings:
            message += "\n\nWarnings:\n" + "\n".join(f"• {warning}" for warning in warnings[:8])
            if len(warnings) > 8:
                message += f"\n• ...and {len(warnings) - 8} more"
        QMessageBox.information(self, "Import", message)
        return True

    def _on_import(self):
        """Choose and import a bookmark JSON file."""
        if not self._current_pdf:
            QMessageBox.warning(self, "No PDF", "Please open a PDF first.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Bookmarks", "", "JSON Files (*.json)"
        )
        if path:
            self._import_from_path(path)
