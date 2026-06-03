"""
QuizSidebar: left panel for Quiz mode.
Shows Current Focus (pinned) and user-created Topics.
"""
import json
import os
import re
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QLabel,
    QPushButton, QMenu, QMessageBox, QInputDialog, QFileDialog,
    QDialog, QFormLayout, QComboBox, QLineEdit, QTextEdit,
    QDialogButtonBox, QProgressDialog, QGroupBox
)
from core import database, api_client
from core.logger import get_logger
from core.theme_colors import get_theme_colors

_logger = get_logger()


class _ImportSourceDialog(QDialog):
    """Dialog to get markdown content via file selection or copy-paste."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Quiz — Source")
        self.setMinimumSize(600, 500)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Top: file selector
        top = QHBoxLayout()
        self.lbl_file = QLabel("<i>No file selected</i>")
        self.lbl_file.setWordWrap(True)
        top.addWidget(self.lbl_file, 1)
        btn_file = QPushButton("📂 Select File")
        btn_file.clicked.connect(self._select_file)
        top.addWidget(btn_file)
        layout.addLayout(top)

        # Text editor for paste
        layout.addWidget(QLabel("Or paste markdown content below:"))
        self.edit_text = QTextEdit(self)
        self.edit_text.setPlaceholderText("Paste quiz markdown here...")
        layout.addWidget(self.edit_text, 1)

        # Buttons
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setText("🤖 Parse with AI")
        btn_box.accepted.connect(self._on_ok)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self._file_path = ""

    def _select_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Markdown", "", "Markdown (*.md)")
        if path:
            self._file_path = path
            self.lbl_file.setText(f"<b>File:</b> {os.path.basename(path)}")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.edit_text.setPlainText(f.read())
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to read file:\n{e}")

    def _on_ok(self):
        text = self.edit_text.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Empty", "Please provide markdown content.")
            return
        self.accept()

    def get_text(self) -> str:
        return self.edit_text.toPlainText().strip()

    def get_file_path(self) -> str:
        return self._file_path


class _ImportPreviewDialog(QDialog):
    def __init__(self, questions: list, topics: list, default_title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Preview")
        self.setMinimumSize(520, 480)
        self.questions = questions
        self.selected_topic_id = None
        self.batch_title = ""

        layout = QVBoxLayout(self)

        info = QLabel(f"<b>{len(questions)}</b> question(s) extracted.")
        layout.addWidget(info)

        # Target topic
        form = QFormLayout()
        self.combo_topic = QComboBox(self)
        self.combo_topic.addItem("-- New Topic --", None)
        for t in topics:
            self.combo_topic.addItem(t["name"], t["id"])
        form.addRow("Target Topic:", self.combo_topic)

        self.edit_new_topic = QLineEdit(self)
        self.edit_new_topic.setPlaceholderText("New topic name (if selected above)")
        form.addRow("New Topic Name:", self.edit_new_topic)

        self.edit_title = QLineEdit(self)
        self.edit_title.setText(default_title)
        form.addRow("Batch Title:", self.edit_title)
        layout.addLayout(form)

        # Preview first question
        preview = QGroupBox("First Question Preview")
        pv_layout = QVBoxLayout(preview)
        if questions:
            q = questions[0]
            txt = f"<b>Q{q.get('number', 1)}:</b> {q.get('text', '')[:300]}...<br>"
            for k, v in sorted(q.get("options", {}).items()):
                txt += f"{k}. {v}<br>"
            txt += f"<b>Answer:</b> {q.get('correct_answer', '?')}"
            pv_layout.addWidget(QLabel(txt))
        else:
            pv_layout.addWidget(QLabel("No questions found."))
        layout.addWidget(preview)

        # JSON raw preview
        raw = QTextEdit(self)
        raw.setPlainText(json.dumps(questions, ensure_ascii=False, indent=2))
        raw.setMaximumHeight(120)
        raw.setReadOnly(True)
        layout.addWidget(QLabel("<b>Raw JSON:</b>"))
        layout.addWidget(raw)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self._on_ok)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _on_ok(self):
        self.batch_title = self.edit_title.text().strip()
        if not self.batch_title:
            QMessageBox.warning(self, "Invalid", "Batch title is required.")
            return
        idx = self.combo_topic.currentIndex()
        self.selected_topic_id = self.combo_topic.itemData(idx)
        if self.selected_topic_id is None:
            name = self.edit_new_topic.text().strip()
            if not name:
                QMessageBox.warning(self, "Invalid", "New topic name is required.")
                return
            self.selected_topic_id = database.create_quiz_topic(name)
        self.accept()


class QuizSidebar(QWidget):
    focus_selected = Signal()
    topic_selected = Signal(int, str)  # topic_id, topic_name
    topic_renamed = Signal(int, str)
    topic_deleted = Signal(int)
    import_completed = Signal(int, str)  # batch_id, title

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(220)
        self.setMaximumWidth(320)
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(8)

        # Header
        header = QLabel("<b>🎯 Quiz Explorer</b>")
        header.setStyleSheet("font-size: 14px; padding-bottom: 4px;")
        layout.addWidget(header)

        # Current Focus (special item)
        self.btn_focus = QPushButton("⭐ Current Focus", self)
        self._apply_focus_style(False)
        self.btn_focus.clicked.connect(self.focus_selected.emit)
        layout.addWidget(self.btn_focus)

        # Separator label
        sep = QLabel("<span style='color:#888;'>Topics</span>")
        layout.addWidget(sep)

        # Topic list
        self.topic_list = QListWidget(self)
        self._apply_list_style()
        self.topic_list.itemClicked.connect(self._on_item_clicked)
        self.topic_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.topic_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.topic_list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.topic_list, 1)

        # Import button
        self.btn_import = QPushButton("📥 Import Markdown (AI)", self)
        self._apply_import_style()
        self.btn_import.clicked.connect(self._on_import_md)
        layout.addWidget(self.btn_import)

        # New topic button
        self.btn_new = QPushButton("+ New Topic", self)
        self._apply_newtopic_style()
        self.btn_new.clicked.connect(self._on_new_topic)
        layout.addWidget(self.btn_new)

    # ------------------------------------------------------------------ #
    # Data
    # ------------------------------------------------------------------ #

    def refresh(self):
        self.topic_list.clear()
        topics = database.get_all_quiz_topics()
        for t in topics:
            item = QListWidgetItem(t["name"])
            item.setData(Qt.ItemDataRole.UserRole, t["id"])
            item.setToolTip(t.get("description", ""))
            self.topic_list.addItem(item)
        # Re-apply theme-aware styles
        self._apply_focus_style(False)
        self._apply_list_style()
        self._apply_import_style()
        self._apply_newtopic_style()

    def _apply_focus_style(self, selected: bool):
        t = get_theme_colors()
        bg = t["selected"] if selected else t["bg"]
        self.btn_focus.setStyleSheet(
            f"QPushButton {{ text-align: left; padding: 8px; border-radius: 4px; "
            f"background: {bg}; color: {t['text']}; font-weight: bold; border: none; }}"
            f"QPushButton:hover {{ background: {t['hover']}; }}"
        )

    def _apply_list_style(self):
        t = get_theme_colors()
        self.topic_list.setStyleSheet(
            f"QListWidget {{ border: none; background: transparent; color: {t['text']}; }}"
            f"QListWidget::item {{ padding: 6px; border-radius: 4px; }}"
            f"QListWidget::item:selected {{ background: {t['selected']}; }}"
            f"QListWidget::item:hover {{ background: {t['hover']}; }}"
        )

    def _apply_import_style(self):
        t = get_theme_colors()
        self.btn_import.setStyleSheet(
            f"QPushButton {{ padding: 6px; border-radius: 4px; background: {t['import_bg']}; "
            f"border: none; color: {t['text']}; }}"
            f"QPushButton:hover {{ background: {t['import_hover']}; }}"
        )

    def _apply_newtopic_style(self):
        t = get_theme_colors()
        self.btn_new.setStyleSheet(
            f"QPushButton {{ padding: 6px; border-radius: 4px; background: {t['bg']}; "
            f"border: none; color: {t['text']}; }}"
            f"QPushButton:hover {{ background: {t['hover']}; }}"
        )

    def select_focus(self):
        self.topic_list.clearSelection()
        self._apply_focus_style(True)

    def deselect_focus(self):
        self._apply_focus_style(False)

    # ------------------------------------------------------------------ #
    # Slots
    # ------------------------------------------------------------------ #

    def _on_item_clicked(self, item: QListWidgetItem):
        self.deselect_focus()
        tid = item.data(Qt.ItemDataRole.UserRole)
        self.topic_selected.emit(tid, item.text())

    def _on_item_double_clicked(self, item: QListWidgetItem):
        self._rename_item(item)

    def _show_context_menu(self, pos):
        item = self.topic_list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        action_rename = menu.addAction("✏️ Rename")
        action_delete = menu.addAction("🗑 Delete")

        tid = item.data(Qt.ItemDataRole.UserRole)
        pinned = database.is_topic_pinned(tid)
        action_pin = menu.addAction("📌 Unpin from Focus" if pinned else "📌 Pin to Focus")

        action = menu.exec(self.topic_list.mapToGlobal(pos))
        if action == action_rename:
            self._rename_item(item)
        elif action == action_delete:
            self._delete_item(item)
        elif action == action_pin:
            if pinned:
                database.unpin_quiz_topic(tid)
            else:
                database.pin_quiz_topic(tid)

    def _rename_item(self, item: QListWidgetItem):
        tid = item.data(Qt.ItemDataRole.UserRole)
        text, ok = QInputDialog.getText(self, "Rename Topic", "New name:", text=item.text())
        if ok and text.strip():
            database.rename_quiz_topic(tid, text.strip())
            item.setText(text.strip())
            self.topic_renamed.emit(tid, text.strip())

    def _delete_item(self, item: QListWidgetItem):
        tid = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(self, "Confirm", "Delete this topic and all its batches?")
        if reply == QMessageBox.StandardButton.Yes:
            database.delete_quiz_topic(tid)
            self.topic_list.takeItem(self.topic_list.row(item))
            self.topic_deleted.emit(tid)

    def _on_new_topic(self):
        text, ok = QInputDialog.getText(self, "New Topic", "Topic name:")
        if ok and text.strip():
            database.create_quiz_topic(text.strip())
            self.refresh()

    # ------------------------------------------------------------------ #
    # AI Import
    # ------------------------------------------------------------------ #

    def _on_import_md(self):
        # Step 1: get source text (file or paste)
        src_dlg = _ImportSourceDialog(self)
        if src_dlg.exec() != QDialog.DialogCode.Accepted:
            return

        text = src_dlg.get_text()
        file_path = src_dlg.get_file_path()

        if not text.strip():
            QMessageBox.warning(self, "Empty", "No content to parse.")
            return

        provider = database.get_default_ai_provider()
        if not provider or not provider.get("api_key"):
            QMessageBox.warning(self, "No AI Provider", "Please configure an AI provider in Settings first.")
            return

        # Step 2: AI parse
        progress = QProgressDialog("Parsing with AI...", "Cancel", 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()

        try:
            questions = self._ai_parse_quiz(text, provider)
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "AI Parse Error", f"Failed to parse quiz:\n{e}")
            return

        progress.close()

        if not questions:
            QMessageBox.warning(self, "No Questions", "AI did not extract any valid questions from the content.")
            return

        # Step 3: Preview / confirm
        topics = database.get_all_quiz_topics()
        default_title = os.path.splitext(os.path.basename(file_path))[0] if file_path else "Imported Batch"
        dlg = _ImportPreviewDialog(questions, topics, default_title, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        topic_id = dlg.selected_topic_id
        title = dlg.batch_title

        batch_id = database.create_quiz_batch(
            topic_id=topic_id,
            title=title,
            source_file_path=file_path,
            question_count=len(questions)
        )

        for q in questions:
            database.create_quiz_question(
                batch_id=batch_id,
                question_number=q.get("number", 1),
                question_text=q.get("text", ""),
                options=q.get("options", {}),
                correct_answer=q.get("correct_answer", ""),
                explanation=q.get("explanation", ""),
                is_multiple_choice=q.get("is_multiple_choice", False)
            )

        self.refresh()
        self.import_completed.emit(batch_id, title)
        QMessageBox.information(self, "Import Complete",
                                f"Imported {len(questions)} questions into '{title}'.")

    def _fix_json_escapes(self, text: str) -> str:
        r"""Fix unescaped backslashes in JSON string values.
        AI often outputs LaTeX like \frac, \sum without double-escaping them
        for JSON. We protect already-valid JSON escapes (\", \\, \n) then
        replace any remaining single backslashes with double backslashes.
        """
        import uuid
        p_quote = f"__Q_{uuid.uuid4().hex}__"
        p_dbl   = f"__D_{uuid.uuid4().hex}__"
        p_nl    = f"__N_{uuid.uuid4().hex}__"

        # Protect already-correct escapes
        text = text.replace('\\"', p_quote)
        text = text.replace('\\\\', p_dbl)
        text = text.replace('\\n', p_nl)

        # Any remaining single backslash is unescaped
        text = text.replace('\\', '\\\\')

        # Restore protected sequences
        text = text.replace(p_quote, '\\"')
        text = text.replace(p_dbl, '\\\\')
        text = text.replace(p_nl, '\\n')
        return text

    def _ai_parse_quiz(self, text: str, provider: dict) -> list:
        prompt = (
            "You are a quiz parser. Extract all questions from the following markdown content.\n"
            "Return ONLY a JSON array in this exact format (no markdown code fences, no extra text):\n"
            '[\n'
            '  {\n'
            '    "number": 1,\n'
            '    "text": "question text in markdown",\n'
            '    "options": {"A": "option A text", "B": "option B text", ...},\n'
            '    "correct_answer": "B",\n'
            '    "explanation": "explanation text, can be empty string",\n'
            '    "is_multiple_choice": false\n'
            '  }\n'
            ']\n'
            "For multiple-choice questions, correct_answer may contain multiple letters like 'A,C'.\n"
            "Set is_multiple_choice to true when there are multiple correct answers.\n"
            "If a question lacks an explanation, use empty string.\n"
            "IMPORTANT: If any text contains LaTeX math with backslashes (like \\frac, \\sum), "
            "the backslashes inside JSON string values MUST be doubled (\\ -> \\\\ ) so they survive JSON parsing.\n\n"
            "Markdown content:\n"
            "---\n"
            f"{text}\n"
            "---"
        )
        messages = [
            {"role": "system", "content": "You are a precise quiz extraction assistant. Output only valid JSON."},
            {"role": "user", "content": prompt},
        ]
        result = api_client.explain_chat(
            messages=messages,
            base_url=provider["base_url"],
            api_key=provider["api_key"],
            model=provider["model"],
            proxy=provider.get("proxy", "")
        )
        if result.startswith("Error:"):
            raise RuntimeError(result)

        # Strip markdown code fences if present
        raw = result.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        # Fix unescaped backslashes in JSON string values (LaTeX often has \left, \sum, etc.)
        raw = self._fix_json_escapes(raw)

        data = json.loads(raw)
        if isinstance(data, dict) and "questions" in data:
            data = data["questions"]
        if not isinstance(data, list):
            raise RuntimeError(f"AI returned unexpected format: {type(data).__name__}")
        return data
