"""
QuizBatchWidget: browse / quiz dual-mode panel for a single batch.
"""
import json
import time
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QButtonGroup, QRadioButton, QCheckBox,
    QStackedWidget, QProgressBar, QTextEdit, QMessageBox, QSplitter,
    QSizePolicy, QSpacerItem, QGridLayout
)
from core import database
from core.logger import get_logger
from core.theme_colors import get_theme_colors
from ui.quiz_renderer import QuizRenderer, render_math_in_text

_logger = get_logger()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# Browse mode: collapsible question card
# ---------------------------------------------------------------------------

class _QuestionCard(QFrame):
    note_changed = Signal(int, str)  # question_id, note_text

    def __init__(self, question: dict, show_answer: bool = False, parent=None):
        super().__init__(parent)
        self.question_id = question["id"]
        self.question_data = question
        self._show_answer = show_answer
        self._setup_ui()

    def _setup_ui(self):
        colors = get_theme_colors()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"QFrame {{ background: {colors['card_bg']}; border-radius: 6px; border: 1px solid {colors['border']}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Header: Q{n} + toggle
        header = QHBoxLayout()
        qnum = self.question_data.get("question_number", 0)
        self.lbl_header = QLabel(f"<b>Q{qnum}</b>")
        self.lbl_header.setStyleSheet(f"font-size: 14px; color: {colors['text']};")
        header.addWidget(self.lbl_header)
        header.addStretch()

        self.btn_toggle = QPushButton("▼ 答案" if self._show_answer else "▶ 答案", self)
        self.btn_toggle.setFixedSize(60, 28)
        self.btn_toggle.setStyleSheet(
            f"QPushButton {{ border:1px solid {colors['border']}; border-radius:4px; "
            f"background:{colors['hover']}; color:{colors['muted']}; font-size:12px; padding:2px 6px; }}"
            f"QPushButton:hover {{ background:{colors['selected']}; color:{colors['text']}; }}"
        )
        self.btn_toggle.clicked.connect(self._toggle_expand)
        header.addWidget(self.btn_toggle)
        layout.addLayout(header)

        # Question text (QuizRenderer)
        qtext = self.question_data.get("question_text", "")
        media = json.loads(self.question_data.get("image_paths_json", "[]"))
        media_list = [{"type": "img", "path": p} for p in media]
        self.renderer = QuizRenderer(self)
        self.renderer.set_content(qtext, media_list)
        self.renderer.setMinimumHeight(80)
        layout.addWidget(self.renderer)

        # Options (read-only display)
        opts = json.loads(self.question_data.get("options_json", "{}"))
        self._opts_layout = QVBoxLayout()
        correct = self.question_data.get("correct_answer", "")
        for key in sorted(opts.keys()):
            opt_html = render_math_in_text(f"<b>{key}.</b> {opts[key]}")
            lbl = QLabel(opt_html)
            lbl.setWordWrap(True)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            if self._show_answer and key in [c.strip() for c in correct.split(",")]:
                lbl.setStyleSheet(f"color: {colors['success']}; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 16px; padding: 2px;")
            else:
                lbl.setStyleSheet(f"color: {colors['text']}; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 16px; padding: 2px;")
            self._opts_layout.addWidget(lbl)
        layout.addLayout(self._opts_layout)

        # Expandable area (answer + explanation + note)
        self.expand_area = QWidget(self)
        ea_layout = QVBoxLayout(self.expand_area)
        ea_layout.setContentsMargins(0, 0, 0, 0)

        ans = self.question_data.get("correct_answer", "")
        ans_html = render_math_in_text(f"<b>Answer:</b> {ans}")
        self.lbl_answer = QLabel(ans_html)
        self.lbl_answer.setWordWrap(True)
        self.lbl_answer.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_answer.setStyleSheet(f"color: {colors['success']}; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 16px; font-weight: bold;")
        ea_layout.addWidget(self.lbl_answer)

        exp = self.question_data.get("explanation", "")
        if exp:
            exp_html = render_math_in_text(f"<b>Explanation:</b> {exp}")
            self.lbl_explanation = QLabel(exp_html)
            self.lbl_explanation.setWordWrap(True)
            self.lbl_explanation.setTextFormat(Qt.TextFormat.RichText)
            self.lbl_explanation.setStyleSheet(f"color: {colors['text']}; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 16px;")
            ea_layout.addWidget(self.lbl_explanation)

        # Note editor
        note = database.get_quiz_note(self.question_id)
        self.edit_note = QTextEdit(self)
        self.edit_note.setPlaceholderText("Your note...")
        self.edit_note.setPlainText(note)
        self.edit_note.setMaximumHeight(80)
        self.edit_note.textChanged.connect(self._on_note_changed)
        ea_layout.addWidget(QLabel(f"<b>📝 Note</b>"))
        ea_layout.addWidget(self.edit_note)

        layout.addWidget(self.expand_area)
        self.expand_area.setVisible(self._show_answer)

    def _toggle_expand(self):
        self._show_answer = not self._show_answer
        self.expand_area.setVisible(self._show_answer)
        self.btn_toggle.setText("▼ 答案" if self._show_answer else "▶ 答案")

    def _on_note_changed(self):
        text = self.edit_note.toPlainText()
        database.save_quiz_note(self.question_id, text)

    def refresh_theme(self):
        """Re-apply theme colors and re-render math formulas."""
        colors = get_theme_colors()
        self.setStyleSheet(
            f"QFrame {{ background: {colors['card_bg']}; border-radius: 6px; border: 1px solid {colors['border']}; }}"
        )
        self.lbl_header.setStyleSheet(f"font-size: 14px; color: {colors['text']};")
        self.renderer.refresh_theme()

        # Re-render option labels with updated math scale
        opts = json.loads(self.question_data.get("options_json", "{}"))
        correct = self.question_data.get("correct_answer", "")
        correct_keys = [c.strip() for c in correct.split(",")]
        for i, key in enumerate(sorted(opts.keys())):
            lbl = self._opts_layout.itemAt(i).widget()
            if isinstance(lbl, QLabel):
                opt_html = render_math_in_text(f"<b>{key}.</b> {opts[key]}")
                lbl.setText(opt_html)
                if self._show_answer and key in correct_keys:
                    lbl.setStyleSheet(f"color: {colors['success']}; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 16px; padding: 2px;")
                else:
                    lbl.setStyleSheet(f"color: {colors['text']}; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 16px; padding: 2px;")

        # Re-render answer label
        ans = self.question_data.get("correct_answer", "")
        ans_html = render_math_in_text(f"<b>Answer:</b> {ans}")
        self.lbl_answer.setText(ans_html)
        self.lbl_answer.setStyleSheet(f"color: {colors['success']}; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 16px; font-weight: bold;")

        # Re-render explanation label
        exp = self.question_data.get("explanation", "")
        if exp and hasattr(self, 'lbl_explanation'):
            exp_html = render_math_in_text(f"<b>Explanation:</b> {exp}")
            self.lbl_explanation.setText(exp_html)
            self.lbl_explanation.setStyleSheet(f"color: {colors['text']}; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 16px;")


# ---------------------------------------------------------------------------
# Quiz mode: single-question view
# ---------------------------------------------------------------------------

class _QuizOptionItem(QWidget):
    """Custom option row: radio/checkbox indicator + rich-text label (supports math SVG)."""

    def __init__(self, key: str, text: str, is_multi: bool, checked: bool = False, parent=None):
        super().__init__(parent)
        self.key = key
        self.is_multi = is_multi

        colors = get_theme_colors()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        if is_multi:
            self.button = QCheckBox()
        else:
            self.button = QRadioButton()
        self.button.setChecked(checked)
        layout.addWidget(self.button)

        self._raw_text = text
        self.label = QLabel(render_math_in_text(f"<b>{key}.</b> {text}"))
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setStyleSheet(f"color: {colors['text']}; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 16px;")
        self.label.installEventFilter(self)
        layout.addWidget(self.label, 1)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.label and event.type() == QEvent.Type.MouseButtonPress:
            self.button.click()
            return True
        return super().eventFilter(obj, event)

    def isChecked(self) -> bool:
        return self.button.isChecked()

    def setChecked(self, checked: bool):
        self.button.setChecked(checked)

    def refresh_theme(self):
        """Re-render option label with updated math scale."""
        colors = get_theme_colors()
        self.label.setText(render_math_in_text(f"<b>{self.key}.</b> {self._raw_text}"))
        self.label.setStyleSheet(f"color: {colors['text']}; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 16px;")


class _QuizSessionWidget(QWidget):
    finished = Signal(int, int, int)  # attempt_id, score, correct_count

    def __init__(self, batch_id: int, questions: list, parent=None):
        super().__init__(parent)
        self.batch_id = batch_id
        self.questions = questions
        self.total = len(questions)
        self.current_idx = 0
        self.attempt_id = None
        self.start_time = 0
        self.elapsed = 0
        self.answers = {}  # question_id -> "A" / "A,C"
        self._setup_ui()
        self._start_attempt()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Top bar
        top = QHBoxLayout()
        self.lbl_progress = QLabel("1 / 1")
        top.addWidget(self.lbl_progress)
        self.lbl_timer = QLabel("00:00")
        top.addWidget(self.lbl_timer)
        top.addStretch()
        layout.addLayout(top)

        # Progress bar
        self.progress = QProgressBar(self)
        self.progress.setMaximum(self.total)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        # Question area (scrollable)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.question_container = QWidget()
        self.q_layout = QVBoxLayout(self.question_container)
        self.q_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self.question_container)
        layout.addWidget(scroll, 1)

        # Navigation
        nav = QHBoxLayout()
        self.btn_prev = QPushButton("◀ Previous")
        self.btn_prev.clicked.connect(self._prev)
        nav.addWidget(self.btn_prev)
        nav.addStretch()
        self.btn_submit = QPushButton("✅ Submit")
        c = get_theme_colors()
        self.btn_submit.setStyleSheet(f"background:{c['success']};color:#fff;font-weight:bold;")
        self.btn_submit.clicked.connect(self._submit)
        nav.addWidget(self.btn_submit)
        self.btn_next = QPushButton("Next ▶")
        self.btn_next.clicked.connect(self._next)
        nav.addWidget(self.btn_next)
        layout.addLayout(nav)

        # Timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

        self._render_question()

    def _start_attempt(self):
        self.attempt_id = database.create_quiz_attempt(self.batch_id, self.total)
        self.start_time = time.time()

    def _tick(self):
        self.elapsed = int(time.time() - self.start_time)
        self.lbl_timer.setText(_fmt_duration(self.elapsed))

    def _render_question(self):
        # Clear previous widgets
        while self.q_layout.count():
            child = self.q_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not (0 <= self.current_idx < self.total):
            return

        q = self.questions[self.current_idx]
        qid = q["id"]
        opts = json.loads(q.get("options_json", "{}"))
        is_multi = bool(q.get("is_multiple_choice", 0))

        # Question text
        q_md = q.get("question_text", "")
        media = json.loads(q.get("image_paths_json", "[]"))
        media_list = [{"type": "img", "path": p} for p in media]
        self._q_renderer = QuizRenderer(self.question_container)
        self._q_renderer.set_content(q_md, media_list)
        self._q_renderer.setMinimumHeight(80)
        self.q_layout.addWidget(self._q_renderer)

        # Options (custom items with rich-text label for math support)
        self._option_widgets = []
        if is_multi:
            for key in sorted(opts.keys()):
                checked = qid in self.answers and key in self.answers[qid].split(",")
                item = _QuizOptionItem(key, opts[key], is_multi=True, checked=checked)
                self.q_layout.addWidget(item)
                self._option_widgets.append(item)
        else:
            self._btn_group = QButtonGroup(self)
            for key in sorted(opts.keys()):
                checked = qid in self.answers and self.answers[qid] == key
                item = _QuizOptionItem(key, opts[key], is_multi=False, checked=checked)
                self._btn_group.addButton(item.button)
                self.q_layout.addWidget(item)
                self._option_widgets.append(item)

        self.q_layout.addStretch()

        # Update progress label
        self.lbl_progress.setText(f"{self.current_idx + 1} / {self.total}")
        self.progress.setValue(self.current_idx)
        self.btn_prev.setEnabled(self.current_idx > 0)
        self.btn_next.setText("Finish ▶" if self.current_idx == self.total - 1 else "Next ▶")
        self.btn_submit.setVisible(self.current_idx == self.total - 1)

    def _collect_answer(self) -> str:
        is_multi = bool(self.questions[self.current_idx].get("is_multiple_choice", 0))
        if is_multi:
            selected = [w.key for w in self._option_widgets if w.isChecked()]
            return ",".join(sorted(selected))
        else:
            for w in self._option_widgets:
                if w.isChecked():
                    return w.key
            return ""

    def refresh_theme(self):
        """Re-apply theme colors and re-render math formulas."""
        if hasattr(self, '_q_renderer') and hasattr(self._q_renderer, 'refresh_theme'):
            self._q_renderer.refresh_theme()
        for w in getattr(self, '_option_widgets', []):
            if hasattr(w, 'refresh_theme'):
                w.refresh_theme()

    def _save_current(self):
        if not (0 <= self.current_idx < self.total):
            return
        q = self.questions[self.current_idx]
        self.answers[q["id"]] = self._collect_answer()

    def _prev(self):
        self._save_current()
        if self.current_idx > 0:
            self.current_idx -= 1
            self._render_question()

    def _next(self):
        self._save_current()
        if self.current_idx < self.total - 1:
            self.current_idx += 1
            self._render_question()
        else:
            self._submit()

    def _submit(self):
        self._save_current()
        self._timer.stop()

        # Calculate score
        correct_count = 0
        for q in self.questions:
            qid = q["id"]
            correct = q.get("correct_answer", "")
            user = self.answers.get(qid, "")
            is_correct = self._check_answer(correct, user, bool(q.get("is_multiple_choice", 0)))
            if is_correct:
                correct_count += 1
            database.create_quiz_response(
                attempt_id=self.attempt_id,
                question_id=qid,
                selected_answer=user,
                is_correct=is_correct,
                duration_seconds=0,
                confidence_level=3
            )

        score = int(correct_count / self.total * 100) if self.total else 0
        database.complete_quiz_attempt(self.attempt_id, self.elapsed, score, correct_count)
        self.finished.emit(self.attempt_id, score, correct_count)

    def _check_answer(self, correct: str, user: str, is_multi: bool) -> bool:
        if is_multi:
            c_set = set(a.strip() for a in correct.split(",") if a.strip())
            u_set = set(a.strip() for a in user.split(",") if a.strip())
            return c_set == u_set
        return correct.strip() == user.strip()


# ---------------------------------------------------------------------------
# Review widgets
# ---------------------------------------------------------------------------

class _ReviewOptionItem(QWidget):
    """Read-only option row with color-coded correctness."""

    def __init__(self, key: str, text: str, status: str, parent=None):
        super().__init__(parent)
        colors = get_theme_colors()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        # Status indicator circle
        self.indicator = QLabel("●")
        self.indicator.setFixedWidth(20)
        self.indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Option text with math support
        self.label = QLabel(render_math_in_text(f"<b>{key}.</b> {text}"))
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setStyleSheet("font-family: 'Segoe UI', system-ui, sans-serif; font-size: 16px;")
        layout.addWidget(self.indicator)
        layout.addWidget(self.label, 1)

        # Apply status color
        if status == "correct_selected":      # 答对
            self.indicator.setText("✓")
            self.indicator.setStyleSheet(f"color: {colors['success']}; font-size: 16px; font-weight: bold;")
            self.setStyleSheet(f"background: {colors['success']}22; border-radius: 4px;")
        elif status == "correct_missed":      # 漏选
            self.indicator.setText("○")
            self.indicator.setStyleSheet(f"color: {colors['warning']}; font-size: 16px; font-weight: bold;")
            self.setStyleSheet(f"background: {colors['warning']}22; border-radius: 4px;")
        elif status == "wrong_selected":      # 错选
            self.indicator.setText("✗")
            self.indicator.setStyleSheet(f"color: {colors['danger']}; font-size: 16px; font-weight: bold;")
            self.setStyleSheet(f"background: {colors['danger']}22; border-radius: 4px;")
        else:                                  # 无关
            self.indicator.setText(" ")
            self.indicator.setStyleSheet(f"color: {colors['muted']}; font-size: 16px;")


class _ReviewQuestionCard(QFrame):
    def __init__(self, question: dict, response: dict or None, parent=None):
        super().__init__(parent)
        self.question = question
        self.response = response
        self._setup_ui()

    def _setup_ui(self):
        # Clear existing layout and widgets for rebuild (used by refresh_theme)
        while self.layout():
            old_layout = self.layout()
            while old_layout.count():
                child = old_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            # Reparent layout items then delete layout
            QWidget().setLayout(old_layout)

        colors = get_theme_colors()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"QFrame {{ background: {colors['card_bg']}; border-radius: 6px; border: 1px solid {colors['border']}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header: Q{n} + correctness icon
        header = QHBoxLayout()
        qnum = self.question.get("question_number", 0)
        is_correct = self.response and self.response.get("is_correct", False)
        icon = "✅" if is_correct else "❌"
        header_lbl = QLabel(f"{icon} <b>Q{qnum}</b>")
        header_lbl.setStyleSheet(f"font-size: 16px; color: {colors['text']};")
        header.addWidget(header_lbl)
        header.addStretch()
        layout.addLayout(header)

        # Question text
        qtext = self.question.get("question_text", "")
        media = json.loads(self.question.get("image_paths_json", "[]"))
        media_list = [{"type": "img", "path": p} for p in media]
        renderer = QuizRenderer(self)
        renderer.set_content(qtext, media_list)
        renderer.setMinimumHeight(60)
        layout.addWidget(renderer)

        # Options with color coding
        opts = json.loads(self.question.get("options_json", "{}"))
        correct_str = self.question.get("correct_answer", "")
        correct_set = set(c.strip() for c in correct_str.split(",") if c.strip())
        user_str = self.response.get("selected_answer", "") if self.response else ""
        user_set = set(c.strip() for c in user_str.split(",") if c.strip())

        for key in sorted(opts.keys()):
            if key in correct_set and key in user_set:
                status = "correct_selected"
            elif key in correct_set and key not in user_set:
                status = "correct_missed"
            elif key not in correct_set and key in user_set:
                status = "wrong_selected"
            else:
                status = "neutral"
            item = _ReviewOptionItem(key, opts[key], status)
            layout.addWidget(item)

        # Answer comparison
        ans_text = f"<b>你的答案:</b> {user_str or '-'}  |  <b>正确答案:</b> {correct_str}"
        ans_lbl = QLabel(ans_text)
        ans_lbl.setWordWrap(True)
        ans_lbl.setTextFormat(Qt.TextFormat.RichText)
        if is_correct:
            ans_lbl.setStyleSheet(f"color: {colors['success']}; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 16px; font-weight: bold;")
        else:
            ans_lbl.setStyleSheet(f"color: {colors['danger']}; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 16px; font-weight: bold;")
        layout.addWidget(ans_lbl)

        # Explanation
        exp = self.question.get("explanation", "")
        if exp:
            exp_renderer = QuizRenderer(self)
            exp_renderer.set_content(f"**解析:** {exp}")
            exp_renderer.setMinimumHeight(40)
            layout.addWidget(exp_renderer)

    def refresh_theme(self):
        """Rebuild UI with current theme colors."""
        self._setup_ui()


class _QuizReviewWidget(QWidget):
    """Full review panel for a quiz attempt."""
    back_requested = Signal()
    restart_requested = Signal()

    def __init__(self, attempt_id: int, questions: list, parent=None):
        super().__init__(parent)
        self.attempt_id = attempt_id
        self.questions = questions
        self._setup_ui()

    def _setup_ui(self):
        colors = get_theme_colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top stats bar
        attempt = database.get_quiz_attempt(self.attempt_id)
        score = attempt.get("score", 0) if attempt else 0
        correct = attempt.get("correct_count", 0) if attempt else 0
        total = attempt.get("total_questions", 0) if attempt else 0
        duration = attempt.get("total_duration_seconds", 0) if attempt else 0

        stats = QHBoxLayout()
        stats.setContentsMargins(16, 12, 16, 12)
        stats.setSpacing(20)
        self._stats_w = QWidget()
        self._stats_w.setStyleSheet(f"background: {colors['card_bg']}; border-bottom: 1px solid {colors['border']};")

        lbl_score = QLabel(f"<h2>得分: <span style='color:{colors['success']};'>{score}%</span></h2>")
        lbl_score.setStyleSheet(f"color: {colors['text']};")
        stats.addWidget(lbl_score)

        lbl_detail = QLabel(f"<b>{correct}</b> / {total} 正确  |  用时: {_fmt_duration(duration)}")
        lbl_detail.setStyleSheet(f"color: {colors['muted']}; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 14px;")
        stats.addWidget(lbl_detail)
        stats.addStretch()

        btn_back = QPushButton("← 返回")
        btn_back.clicked.connect(self.back_requested.emit)
        stats.addWidget(btn_back)

        btn_restart = QPushButton("🔄 重新答题")
        btn_restart.clicked.connect(self.restart_requested.emit)
        stats.addWidget(btn_restart)

        self._stats_w.setLayout(stats)
        layout.addWidget(self._stats_w)

        # Scrollable review cards
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(12, 12, 12, 12)
        c_layout.setSpacing(10)

        # Fetch responses
        responses = database.get_quiz_responses_by_attempt(self.attempt_id)
        resp_map = {r["question_id"]: r for r in responses}

        for q in self.questions:
            card = _ReviewQuestionCard(q, resp_map.get(q["id"]))
            c_layout.addWidget(card)

        c_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

    def refresh_theme(self):
        """Re-apply theme colors to all child widgets."""
        colors = get_theme_colors()
        self.setStyleSheet(f"background: {colors['bg']};")
        # Refresh stats bar if accessible
        if hasattr(self, '_stats_w'):
            self._stats_w.setStyleSheet(
                f"background: {colors['card_bg']}; border-bottom: 1px solid {colors['border']};"
            )
        # Refresh all review cards in the scroll area
        scroll = None
        for i in range(self.layout().count()):
            w = self.layout().itemAt(i).widget()
            if isinstance(w, QScrollArea):
                scroll = w
                break
        if scroll and scroll.widget():
            container = scroll.widget()
            for i in range(container.layout().count()):
                item = container.layout().itemAt(i)
                if item and item.widget() and hasattr(item.widget(), 'refresh_theme'):
                    item.widget().refresh_theme()


# ---------------------------------------------------------------------------
# Result panel shown after quiz submission (legacy, kept for compatibility)
# ---------------------------------------------------------------------------

class _ResultPanel(QWidget):
    restart_requested = Signal()

    def __init__(self, attempt_id: int, score: int, correct_count: int, total: int, duration: int, parent=None):
        super().__init__(parent)
        self._setup_ui(attempt_id, score, correct_count, total, duration)

    def _setup_ui(self, attempt_id, score, correct_count, total, duration):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(QLabel(f"<h1>🎉 Quiz Completed!</h1>"))
        colors = get_theme_colors()
        layout.addWidget(QLabel(f"<h2>Score: <span style='color:{colors['success']};'>{score}%</span></h2>"))
        layout.addWidget(QLabel(f"<b>Correct:</b> {correct_count} / {total}"))
        layout.addWidget(QLabel(f"<b>Duration:</b> {_fmt_duration(duration)}"))

        # Per-question review
        responses = database.get_quiz_responses_by_attempt(attempt_id)
        layout.addWidget(QLabel("<h3>Review</h3>"))
        for r in responses:
            q = database.get_quiz_question(r["question_id"])
            if not q:
                continue
            icon = "✅" if r["is_correct"] else "❌"
            lbl = QLabel(f"{icon} <b>Q{q['question_number']}</b> — Your: {r['selected_answer'] or '-'} | Correct: {q['correct_answer']}")
            layout.addWidget(lbl)

        layout.addStretch()
        btn_restart = QPushButton("🔄 Restart Quiz")
        btn_restart.clicked.connect(self.restart_requested.emit)
        layout.addWidget(btn_restart)


# ---------------------------------------------------------------------------
# QuizBatchWidget (main)
# ---------------------------------------------------------------------------

class QuizBatchWidget(QWidget):
    def __init__(self, batch_id: int, parent=None):
        super().__init__(parent)
        self.batch_id = batch_id
        self.questions = []
        self.attempts = []
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # Top toolbar (mode switch only — title lives in tab bar)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(10, 8, 10, 8)
        toolbar.setSpacing(10)
        toolbar.addStretch()

        self.btn_browse = QPushButton("📖 Browse")
        self.btn_browse.setCheckable(True)
        self.btn_browse.setChecked(True)
        self.btn_browse.clicked.connect(lambda: self._set_mode("browse"))
        toolbar.addWidget(self.btn_browse)

        self.btn_quiz = QPushButton("✏️ Quiz")
        self.btn_quiz.setCheckable(True)
        self.btn_quiz.clicked.connect(lambda: self._set_mode("quiz"))
        toolbar.addWidget(self.btn_quiz)

        # --- Browse toolbar buttons ---
        self.btn_show_all = QPushButton("📖 显示全部答案")
        self.btn_show_all.setCheckable(True)
        self.btn_show_all.setChecked(False)
        self.btn_show_all.clicked.connect(self._toggle_all_answers)
        toolbar.addWidget(self.btn_show_all)
        toolbar.addStretch()

        toolbar_w = QWidget()
        toolbar_w.setLayout(toolbar)
        c = get_theme_colors()
        toolbar_w.setStyleSheet(f"background: {c['base']};")
        main.addWidget(toolbar_w)

        # Stacked content
        self.stack = QStackedWidget(self)

        # Page 0: Browse
        self.scroll_browse = QScrollArea(self)
        self.scroll_browse.setWidgetResizable(True)
        self.scroll_browse.setFrameShape(QFrame.Shape.NoFrame)
        self.browse_container = QWidget()
        self.browse_layout = QVBoxLayout(self.browse_container)
        self.browse_layout.setContentsMargins(12, 12, 12, 12)
        self.browse_layout.setSpacing(10)
        self.browse_layout.addStretch()
        self.scroll_browse.setWidget(self.browse_container)
        self.stack.addWidget(self.scroll_browse)

        # Page 1: Quiz placeholder (will be replaced dynamically)
        self.quiz_placeholder = QWidget()
        qp_layout = QVBoxLayout(self.quiz_placeholder)
        qp_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_start = QPushButton("▶ Start Quiz")
        self.btn_start.setStyleSheet("font-size:18px;padding:12px 24px;")
        self.btn_start.clicked.connect(self._start_quiz)
        qp_layout.addWidget(self.btn_start)
        self.stack.addWidget(self.quiz_placeholder)

        # Page 2: Result panel (dynamic)
        self.result_panel = None

        main.addWidget(self.stack, 1)

        # History footer (clickable attempt list)
        self.history_container = QWidget()
        self.history_layout = QHBoxLayout(self.history_container)
        self.history_layout.setContentsMargins(10, 6, 10, 6)
        self.history_layout.setSpacing(8)
        self.history_layout.addStretch()
        main.addWidget(self.history_container)

    def _load_data(self):
        batch = database.get_quiz_batch(self.batch_id)
        self.questions = database.get_quiz_questions_by_batch(self.batch_id)
        self._populate_browse()
        self._load_history()

    def _populate_browse(self):
        # Remove old cards (preserve stretch)
        while self.browse_layout.count() > 1:
            child = self.browse_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        for q in self.questions:
            card = _QuestionCard(q, show_answer=False)
            self.browse_layout.insertWidget(self.browse_layout.count() - 1, card)

    def _load_history(self):
        # Clear old history widgets
        while self.history_layout.count():
            child = self.history_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        colors = get_theme_colors()
        attempts = database.get_quiz_attempts_by_batch(self.batch_id)

        if not attempts:
            lbl = QLabel("暂无答题记录")
            lbl.setStyleSheet(f"color:{colors['muted']};font-family:'Segoe UI',system-ui,sans-serif;font-size:13px;")
            self.history_layout.addWidget(lbl)
            self.history_layout.addStretch()
            return

        lbl = QLabel(f"答题记录 ({len(attempts)}次):")
        lbl.setStyleSheet(f"color:{colors['muted']};font-family:'Segoe UI',system-ui,sans-serif;font-size:13px;")
        self.history_layout.addWidget(lbl)

        for i, att in enumerate(attempts):
            score = att.get("score", 0)
            correct = att.get("correct_count", 0)
            total = att.get("total_questions", 0)
            date = att.get("started_at", "")[:10]  # YYYY-MM-DD
            btn = QPushButton(f"#{len(attempts)-i} {date} {score}% ({correct}/{total})")
            btn.setFlat(True)
            btn.setStyleSheet(
                f"QPushButton {{ color:{colors['accent']}; font-size:12px; padding:2px 8px; "
                f"border:1px solid {colors['border']}; border-radius:4px; background:transparent; }}"
                f"QPushButton:hover {{ background:{colors['hover']}; }}"
            )
            btn.setProperty("attempt_id", att["id"])
            btn.clicked.connect(lambda checked, aid=att["id"]: self._show_attempt_review(aid))
            self.history_layout.addWidget(btn)

        self.history_layout.addStretch()

    def _show_attempt_review(self, attempt_id: int):
        """Show review for a historical attempt."""
        # Remove current widget at index 1 if any
        if self.stack.widget(1) is not self.quiz_placeholder:
            old = self.stack.widget(1)
            self.stack.removeWidget(old)
            old.deleteLater()

        review = _QuizReviewWidget(attempt_id, self.questions, self)
        review.restart_requested.connect(self._start_quiz)
        review.back_requested.connect(lambda: self._set_mode("browse"))
        self.stack.insertWidget(1, review)
        self.stack.setCurrentIndex(1)
        self.btn_browse.setChecked(False)
        self.btn_quiz.setChecked(False)

    def _set_mode(self, mode: str):
        if mode == "browse":
            self.btn_browse.setChecked(True)
            self.btn_quiz.setChecked(False)
            self.stack.setCurrentIndex(0)
        else:
            self.btn_browse.setChecked(False)
            self.btn_quiz.setChecked(True)
            # If quiz session already active, show it; otherwise show start button
            if self.stack.count() >= 2 and self.stack.widget(1) is not self.quiz_placeholder:
                # Check if result panel is current
                pass
            self.stack.setCurrentIndex(1)

    def _start_quiz(self):
        if not self.questions:
            QMessageBox.warning(self, "Empty", "No questions in this batch.")
            return
        # Replace placeholder with real quiz session
        if self.stack.widget(1) is not self.quiz_placeholder:
            old = self.stack.widget(1)
            self.stack.removeWidget(old)
            old.deleteLater()

        session = _QuizSessionWidget(self.batch_id, self.questions, self)
        session.finished.connect(self._on_quiz_finished)
        self.stack.insertWidget(1, session)
        self.stack.setCurrentIndex(1)

    def _toggle_all_answers(self):
        show = self.btn_show_all.isChecked()
        self.btn_show_all.setText("📖 隐藏全部答案" if show else "📖 显示全部答案")
        for i in range(self.browse_layout.count()):
            item = self.browse_layout.itemAt(i)
            if item and item.widget():
                card = item.widget()
                if hasattr(card, '_show_answer'):
                    card._show_answer = show
                    card.expand_area.setVisible(show)
                    card.btn_toggle.setText("▼ 答案" if show else "▶ 答案")
                    if show:
                        card.refresh_theme()

    def refresh_theme(self):
        """Re-apply theme colors to all child widgets."""
        for i in range(self.browse_layout.count()):
            item = self.browse_layout.itemAt(i)
            if item and item.widget():
                card = item.widget()
                if hasattr(card, 'refresh_theme'):
                    card.refresh_theme()
        # Refresh active quiz session if present
        w = self.stack.widget(1)
        if w and hasattr(w, 'refresh_theme'):
            w.refresh_theme()

    def _on_quiz_finished(self, attempt_id: int, score: int, correct_count: int):
        # Remove quiz session, show detailed review
        old = self.stack.widget(1)
        self.stack.removeWidget(old)
        old.deleteLater()

        review = _QuizReviewWidget(attempt_id, self.questions, self)
        review.restart_requested.connect(self._start_quiz)
        review.back_requested.connect(lambda: self._set_mode("browse"))
        self.stack.insertWidget(1, review)
        self.stack.setCurrentIndex(1)
        self._load_history()
