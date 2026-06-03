"""
Folder tree explorer for the Sidebar (VSCode-style).
"""
import os
import re
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem


class ExplorerTree(QTreeWidget):
    """
    Displays a folder tree. Double-clicking a PDF file emits file_selected.
    """
    file_selected = Signal(str)  # absolute path of selected file
    folder_selected = Signal(str)  # absolute path of root folder

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.setAnimated(True)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.itemExpanded.connect(self._on_item_expanded)
        self._root_path = ""

    def set_root(self, path: str):
        """Populate the tree with the given folder's contents."""
        self.clear()
        self._root_path = path
        if not path or not os.path.isdir(path):
            return
        self.folder_selected.emit(path)
        root_item = QTreeWidgetItem(self)
        root_item.setText(0, os.path.basename(path) or path)
        root_item.setData(0, Qt.ItemDataRole.UserRole, path)
        root_item.setExpanded(True)
        self._populate(root_item, path)

    @staticmethod
    def _natural_key(s: str):
        """Natural sort key: file2.txt comes before file10.txt."""
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

    def _populate(self, parent_item: QTreeWidgetItem, path: str):
        try:
            entries = sorted(
                os.listdir(path),
                key=lambda s: (not os.path.isdir(os.path.join(path, s)), self._natural_key(s))
            )
        except OSError:
            return
        for entry in entries:
            if entry.startswith("."):
                continue
            full = os.path.join(path, entry)
            child = QTreeWidgetItem(parent_item)
            child.setText(0, entry)
            child.setData(0, Qt.ItemDataRole.UserRole, full)
            if os.path.isdir(full):
                child.setText(0, f"📁 {entry}")
                # Add a dummy child so the expand arrow appears; we'll lazy-load on expand
                dummy = QTreeWidgetItem(child)
                dummy.setText(0, "")
            else:
                icon = "📄"
                if entry.lower().endswith(".pdf"):
                    icon = "📕"
                child.setText(0, f"{icon} {entry}")

    def _on_item_expanded(self, item: QTreeWidgetItem):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path or not os.path.isdir(path):
            return
        # If first child is dummy (no data), replace with real contents
        if item.childCount() == 1:
            first = item.child(0)
            if first.data(0, Qt.ItemDataRole.UserRole) is None:
                item.takeChild(0)
                self._populate(item, path)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        if os.path.isfile(path) and path.lower().endswith(".pdf"):
            self.file_selected.emit(path)
