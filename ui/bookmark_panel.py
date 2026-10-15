"""
Bookmark panel with tree structure, drag-and-drop reordering, and import/export.
"""
import json
import os
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal, QMimeData, QByteArray
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
            database.add_bookmark(
                self._current_pdf,
                0,  # page_number placeholder
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
        layout.addWidget(self.tree)

        # Export / Import buttons
        btn_layout = QHBoxLayout()
        self.btn_export = QPushButton("📤 Export")
        self.btn_export.clicked.connect(self._on_export)
        self.btn_import = QPushButton("📥 Import")
        self.btn_import.clicked.connect(self._on_import)
        btn_layout.addWidget(self.btn_export)
        btn_layout.addWidget(self.btn_import)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        layout.addStretch()

    def set_pdf(self, pdf_path: str):
        """Set the current PDF and reload bookmarks."""
        self._current_pdf = pdf_path
        self.tree.set_pdf(pdf_path)

    def set_current_page(self, page_number: int):
        """Update the current page number for 'Add Current Page' button."""
        self._current_page = page_number

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

    def _on_import(self):
        """Import bookmarks from a JSON file."""
        if not self._current_pdf:
            QMessageBox.warning(self, "No PDF", "Please open a PDF first.")
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Import Bookmarks", "", "JSON Files (*.json)"
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to read file:\n{e}")
            return

        bookmarks = data.get("bookmarks", [])
        if not isinstance(bookmarks, list):
            QMessageBox.critical(self, "Import Error", "Invalid bookmark file format.")
            return

        # Clear existing bookmarks
        existing = database.get_bookmarks(self._current_pdf)
        for bm in existing:
            database.delete_bookmark(bm["id"])

        # Import recursively
        def _import_tree(items: List[Dict], parent_id: int = 0):
            for item in items:
                title = item.get("title", "Untitled")
                page = item.get("page_number", 0)
                entry_type = item.get("entry_type", "bookmark")
                new_id = database.add_bookmark(
                    self._current_pdf, page, title, parent_id, entry_type
                )
                children = item.get("children", [])
                if children:
                    _import_tree(children, new_id)

        _import_tree(bookmarks)
        self.tree.set_pdf(self._current_pdf)
        self.structure_changed.emit()
        QMessageBox.information(self, "Import", "Bookmarks imported successfully.")
