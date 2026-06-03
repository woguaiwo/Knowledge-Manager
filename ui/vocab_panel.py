"""
Right-side panel showing vocabulary list and AI generation controls.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QTextEdit,
    QMessageBox, QHeaderView, QComboBox
)

from core import database, api_client


class VocabPanel(QWidget):
    request_generate = Signal(int)   # provider_id
    vocab_changed = Signal()         # emitted when entries are added or removed
    vocab_saved = Signal(str)        # emitted with file path when saved to JSON

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_pdf_path = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.title_label = QLabel("📚 Vocabulary Collection")
        self.title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(self.title_label)

        self.stats_label = QLabel("Words: 0 | Phrases: 0 | Sentences: 0")
        layout.addWidget(self.stats_label)

        self.auto_save_label = QLabel("💾 Auto-saved to local database")
        self.auto_save_label.setStyleSheet("font-size: 11px; color: #888888;")
        layout.addWidget(self.auto_save_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Word/Phrase", "Type", "Page", "Context", "Definition"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        # AI Provider selector + Generate button
        ai_layout = QHBoxLayout()
        ai_layout.addWidget(QLabel("AI:"))
        self.combo_provider = QComboBox()
        self.combo_provider.setMinimumWidth(150)
        ai_layout.addWidget(self.combo_provider)
        self.btn_generate = QPushButton("🤖 Generate Explanations")
        ai_layout.addWidget(self.btn_generate)
        ai_layout.addStretch()
        layout.addLayout(ai_layout)

        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("💾 Save")
        self.btn_remove = QPushButton("❌ Remove Selected")
        self.btn_clear = QPushButton("🗑 Clear All")
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_remove)
        btn_layout.addWidget(self.btn_clear)
        layout.addLayout(btn_layout)

        self.result_area = QTextEdit()
        self.result_area.setPlaceholderText("AI generated explanations will appear here...")
        self.result_area.setReadOnly(True)
        layout.addWidget(QLabel("Generated Result:"))
        layout.addWidget(self.result_area)

        self.btn_generate.clicked.connect(self._on_generate)
        self.btn_save.clicked.connect(self._on_save)
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_remove.clicked.connect(self._on_remove)

        self.setLayout(layout)
        self._refresh_providers()

    def _refresh_providers(self):
        self.combo_provider.clear()
        providers = database.get_all_ai_providers()
        for p in providers:
            label = f"{p['name']} ({p['model']})"
            if p.get("is_default"):
                label += " ⭐"
            self.combo_provider.addItem(label, p["id"])
        # Select default
        for i in range(self.combo_provider.count()):
            pid = self.combo_provider.itemData(i)
            for p in providers:
                if p["id"] == pid and p.get("is_default"):
                    self.combo_provider.setCurrentIndex(i)
                    break

    def set_pdf(self, pdf_path: str):
        self.current_pdf_path = pdf_path
        self.refresh()
        self._refresh_providers()

    def refresh(self):
        self.table.setRowCount(0)
        if not self.current_pdf_path:
            self.stats_label.setText("Words: 0 | Phrases: 0 | Sentences: 0")
            return
        words = database.get_vocabulary(self.current_pdf_path)
        counts = {"word": 0, "phrase": 0, "sentence": 0}
        for entry in words:
            row = self.table.rowCount()
            self.table.insertRow(row)
            item_word = QTableWidgetItem(entry["word"])
            item_word.setData(Qt.ItemDataRole.UserRole, entry["id"])
            self.table.setItem(row, 0, item_word)
            etype = entry.get("entry_type", "word")
            self.table.setItem(row, 1, QTableWidgetItem(etype.capitalize()))
            self.table.setItem(row, 2, QTableWidgetItem(str(entry["page_number"])))
            self.table.setItem(row, 3, QTableWidgetItem(entry.get("context", "")))
            self.table.setItem(row, 4, QTableWidgetItem(entry.get("definition", "")))
            counts[etype] = counts.get(etype, 0) + 1
        self.stats_label.setText(
            f"Words: {counts.get('word', 0)} | "
            f"Phrases: {counts.get('phrase', 0)} | "
            f"Sentences: {counts.get('sentence', 0)}"
        )

    def _on_generate(self):
        provider_id = self.combo_provider.currentData()
        if provider_id is None:
            QMessageBox.warning(self, "Warning", "No AI provider configured. Please open Settings.")
            return
        self.request_generate.emit(provider_id)

    def show_generated_result(self, text: str):
        self.result_area.setPlainText(text)
        # Try to parse structured results and update definitions in DB
        definitions = api_client.parse_definitions(text)
        if definitions:
            updated = 0
            for d in definitions:
                word = d.get("word", "")
                if not word:
                    continue
                # Find matching vocab entry for current PDF
                words = database.get_vocabulary(self.current_pdf_path)
                for entry in words:
                    if entry["word"].lower() == word.lower():
                        en = d.get("explanation_en", "")
                        cn = d.get("explanation_cn", "")
                        combined = f"{en}\n{cn}".strip()
                        database.update_vocabulary(entry["id"], definition=combined)
                        updated += 1
                        break
            if updated > 0:
                self.refresh()
                self.stats_label.setText(self.stats_label.text() + f" | Definitions updated: {updated}")

    def _on_save(self):
        if not self.current_pdf_path:
            QMessageBox.information(self, "Info", "No PDF loaded.")
            return
        words = database.get_vocabulary(self.current_pdf_path)
        if not words:
            reply = QMessageBox.question(
                self, "Confirm", "No vocabulary to save. Save empty file?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        try:
            path = database.save_vocab_to_file(self.current_pdf_path)
            self.vocab_saved.emit(path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {e}")

    def _on_remove(self):
        selected = self.table.selectedItems()
        if not selected:
            return
        rows = set(item.row() for item in selected)
        removed = 0
        for row in sorted(rows, reverse=True):
            item = self.table.item(row, 0)
            if item is None:
                continue
            entry_id = item.data(Qt.ItemDataRole.UserRole)
            if entry_id:
                database.remove_vocabulary(entry_id)
                removed += 1
        if removed:
            self.refresh()
            self.vocab_changed.emit()

    def _on_clear(self):
        if not self.current_pdf_path:
            return
        reply = QMessageBox.question(
            self, "Confirm", "Clear all vocabulary for this document?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            database.clear_vocabulary(self.current_pdf_path)
            self.refresh()
            self.vocab_changed.emit()
