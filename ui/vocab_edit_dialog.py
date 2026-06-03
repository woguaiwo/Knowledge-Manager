"""
Dialog for editing vocabulary entries (Address Edit).
Allows add, delete, and inline edit of vocabulary items.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QLineEdit, QComboBox,
    QMessageBox, QHeaderView, QAbstractItemView
)

from core import database


class VocabEditDialog(QDialog):
    """
    Modal dialog showing all vocabulary entries for a PDF.
    Supports add / delete / edit inline.
    """
    entries_changed = Signal()

    def __init__(self, pdf_path: str, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.setWindowTitle(f"Edit Vocabulary — {pdf_path}")
        self.resize(800, 500)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        header = QLabel("📝 Address Edit — Double-click a cell to edit, right-click to delete")
        header.setStyleSheet("font-size: 14px; font-weight: bold; padding: 4px;")
        layout.addWidget(header)

        # Table
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Word/Phrase", "Type", "Page", "Context", "Definition", ""])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self.table)

        # Add new entry row
        add_layout = QHBoxLayout()
        self.edit_word = QLineEdit()
        self.edit_word.setPlaceholderText("Word / Phrase")
        self.combo_type = QComboBox()
        self.combo_type.addItems(["Word", "Phrase", "Sentence"])
        self.edit_page = QLineEdit("0")
        self.edit_page.setFixedWidth(50)
        self.edit_context = QLineEdit()
        self.edit_context.setPlaceholderText("Context (optional)")
        self.edit_definition = QLineEdit()
        self.edit_definition.setPlaceholderText("Definition (optional)")
        self.btn_add = QPushButton("➕ Add")
        self.btn_add.clicked.connect(self._on_add)
        add_layout.addWidget(self.edit_word, 2)
        add_layout.addWidget(self.combo_type, 1)
        add_layout.addWidget(self.edit_page, 0)
        add_layout.addWidget(self.edit_context, 2)
        add_layout.addWidget(self.edit_definition, 2)
        add_layout.addWidget(self.btn_add)
        layout.addLayout(add_layout)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        self.btn_save_file = QPushButton("💾 Save to File")
        self.btn_save_file.clicked.connect(self._on_save_file)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_save_file)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

        self.setLayout(layout)
        self._load_entries()

    def _load_entries(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        words = database.get_vocabulary(self.pdf_path)
        for entry in words:
            self._add_row(entry["id"], entry["word"], entry.get("entry_type", "word"),
                          entry["page_number"], entry.get("context", ""), entry.get("definition", ""))
        self.table.blockSignals(False)

    def _add_row(self, entry_id: int, word: str, entry_type: str, page: int, context: str, definition: str):
        row = self.table.rowCount()
        self.table.insertRow(row)

        item_word = QTableWidgetItem(word)
        item_word.setData(Qt.ItemDataRole.UserRole, entry_id)
        self.table.setItem(row, 0, item_word)

        self.table.setItem(row, 1, QTableWidgetItem(entry_type.capitalize()))
        self.table.setItem(row, 2, QTableWidgetItem(str(page)))
        self.table.setItem(row, 3, QTableWidgetItem(context))
        self.table.setItem(row, 4, QTableWidgetItem(definition))

        btn_del = QPushButton("🗑")
        btn_del.setFixedSize(28, 28)
        btn_del.setStyleSheet("QPushButton { border: none; background: transparent; }")
        btn_del.clicked.connect(lambda _=False, r=row: self._on_delete_row(r))
        self.table.setCellWidget(row, 5, btn_del)

    def _on_add(self):
        word = self.edit_word.text().strip()
        if not word:
            return
        entry_type = self.combo_type.currentText().lower()
        try:
            page = int(self.edit_page.text())
        except ValueError:
            page = 0
        context = self.edit_context.text().strip()
        definition = self.edit_definition.text().strip()
        entry_id = database.add_vocabulary(self.pdf_path, word, page, context, entry_type, definition)
        if entry_id:
            self._add_row(entry_id, word, entry_type, page, context, definition)
            self.entries_changed.emit()
            self.edit_word.clear()
            self.edit_context.clear()
            self.edit_definition.clear()
        else:
            QMessageBox.information(self, "Duplicate", f"'{word}' already exists.")

    def _on_delete_row(self, row: int):
        item = self.table.item(row, 0)
        if item is None:
            return
        entry_id = item.data(Qt.ItemDataRole.UserRole)
        if entry_id:
            database.remove_vocabulary(entry_id)
            self.table.removeRow(row)
            self.entries_changed.emit()

    def _on_cell_changed(self, row: int, column: int):
        """Handle inline editing."""
        if row < 0 or row >= self.table.rowCount():
            return
        item_id = self.table.item(row, 0)
        if item_id is None:
            return
        entry_id = item_id.data(Qt.ItemDataRole.UserRole)
        if not entry_id:
            return

        if column == 0:
            new_word = self.table.item(row, 0).text().strip()
            database.update_vocabulary(entry_id, word=new_word)
        elif column == 1:
            new_type = self.table.item(row, 1).text().strip().lower()
            database.update_vocabulary(entry_id, entry_type=new_type)
        elif column == 2:
            try:
                new_page = int(self.table.item(row, 2).text())
                database.update_vocabulary(entry_id, page_number=new_page)
            except ValueError:
                pass
        elif column == 3:
            new_context = self.table.item(row, 3).text().strip()
            database.update_vocabulary(entry_id, context=new_context)
        elif column == 4:
            new_definition = self.table.item(row, 4).text().strip()
            database.update_vocabulary(entry_id, definition=new_definition)

        self.entries_changed.emit()

    def _on_save_file(self):
        try:
            path = database.save_vocab_to_file(self.pdf_path)
            QMessageBox.information(self, "Saved", f"Vocabulary saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {e}")
