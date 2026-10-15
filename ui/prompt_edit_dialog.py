"""
Dialog for viewing and editing user-configurable AI prompts.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QListWidget, QListWidgetItem, QMessageBox, QSizePolicy
)
from PySide6.QtCore import Qt

from core import prompt_manager


PROMPT_LABELS = {
    "prompt_target_reading": "🎯 Target Reading",
    "prompt_explain_selection": "💡 Explain Selection",
    "prompt_explain_image": "🖼️ Explain Image",
    "prompt_explain_page": "📄 Explain Page",
    "prompt_quiz_parser": "📝 Quiz Parser",
    "prompt_definition": "📖 Definition Lookup",
}

PROMPT_HINTS = {
    "prompt_target_reading": {
        "user": "Available placeholders: {question}, {pdf_text}",
    },
    "prompt_explain_selection": {
        "user": "Available placeholders: {selected_text}, {context}",
    },
    "prompt_quiz_parser": {
        "user": "Available placeholders: {content}",
    },
    "prompt_definition": {
        "user": "Available placeholders: {words}",
    },
}


class PromptEditDialog(QDialog):
    """Allow the user to inspect and modify AI prompts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit AI Prompts")
        self.setMinimumSize(720, 540)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        hint = QLabel(
            "Select a prompt on the left to edit. Changes take effect immediately after saving. "
            "Use the placeholders shown in the hint text; they will be replaced at runtime."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        main_layout = QHBoxLayout()

        # Prompt selector
        self.list_prompts = QListWidget()
        self.list_prompts.setMaximumWidth(220)
        for key in prompt_manager.list_prompt_keys():
            item = QListWidgetItem(PROMPT_LABELS.get(key, key))
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.list_prompts.addItem(item)
        self.list_prompts.currentItemChanged.connect(self._on_selection_changed)
        main_layout.addWidget(self.list_prompts)

        # Editor area
        editor_layout = QVBoxLayout()

        self.lbl_name = QLabel("Select a prompt")
        self.lbl_name.setStyleSheet("font-weight: bold; font-size: 14px;")
        editor_layout.addWidget(self.lbl_name)

        editor_layout.addWidget(QLabel("System message:"))
        self.edit_system = QTextEdit()
        self.edit_system.setPlaceholderText("Optional system prompt sent to the AI...")
        self.edit_system.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        editor_layout.addWidget(self.edit_system)

        self.lbl_user_hint = QLabel("")
        self.lbl_user_hint.setStyleSheet("color: gray;")
        self.lbl_user_hint.setWordWrap(True)
        editor_layout.addWidget(self.lbl_user_hint)

        editor_layout.addWidget(QLabel("User / task template:"))
        self.edit_user = QTextEdit()
        self.edit_user.setPlaceholderText("User prompt template...")
        self.edit_user.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        editor_layout.addWidget(self.edit_user)

        main_layout.addLayout(editor_layout, stretch=1)
        layout.addLayout(main_layout, stretch=1)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_reset = QPushButton("↺ Reset to Default")
        self.btn_reset.setToolTip("Restore the built-in prompt for the selected item")
        self.btn_reset.clicked.connect(self._reset_current)
        btn_layout.addWidget(self.btn_reset)

        self.btn_save = QPushButton("💾 Save")
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self._save_current)
        btn_layout.addWidget(self.btn_save)

        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_close)

        layout.addLayout(btn_layout)

        self._current_key = None
        self._current_prompt = {}

        # Select first prompt and load it
        if self.list_prompts.count() > 0:
            self.list_prompts.setCurrentRow(0)

    def _on_selection_changed(self, current: QListWidgetItem, previous):
        # Save pending changes from previous selection automatically
        if previous is not None and self._current_key is not None:
            self._sync_current_to_memory()

        if current is None:
            self._current_key = None
            self._current_prompt = {}
            self.lbl_name.setText("Select a prompt")
            self.edit_system.clear()
            self.edit_user.clear()
            self.lbl_user_hint.setText("")
            return

        key = current.data(Qt.ItemDataRole.UserRole)
        self._current_key = key
        self._current_prompt = prompt_manager.get_prompt(key)
        self.lbl_name.setText(PROMPT_LABELS.get(key, key))
        self.edit_system.setPlainText(self._current_prompt.get("system", ""))
        self.edit_user.setPlainText(self._current_prompt.get("user", ""))
        self.lbl_user_hint.setText(PROMPT_HINTS.get(key, {}).get("user", ""))

    def _sync_current_to_memory(self):
        if self._current_key is None:
            return
        self._current_prompt["system"] = self.edit_system.toPlainText().strip()
        self._current_prompt["user"] = self.edit_user.toPlainText().strip()

    def _save_current(self):
        if self._current_key is None:
            return
        self._sync_current_to_memory()
        prompt_manager.save_prompt(self._current_key, self._current_prompt)
        QMessageBox.information(self, "Saved", "Prompt saved successfully.")

    def _reset_current(self):
        if self._current_key is None:
            return
        reply = QMessageBox.question(
            self,
            "Confirm Reset",
            "Restore the default prompt for this item? Your custom edits will be lost.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._current_prompt = prompt_manager.reset_prompt(self._current_key)
        self.edit_system.setPlainText(self._current_prompt.get("system", ""))
        self.edit_user.setPlainText(self._current_prompt.get("user", ""))
        QMessageBox.information(self, "Reset", "Default prompt restored.")

    def accept(self):
        # Auto-save any pending edits before closing
        self._sync_current_to_memory()
        if self._current_key is not None:
            prompt_manager.save_prompt(self._current_key, self._current_prompt)
        super().accept()
