"""
AI Chat panel for general-purpose conversation.
Shares the left slot with Explorer in the central layout.
Supports named persistent sessions, provider selection, streaming output,
drag-and-drop / paste image upload, and token estimation.
"""
import base64
import json
from PySide6.QtCore import Qt, QThread, Signal as QSignal, QByteArray, QBuffer, QEvent
from PySide6.QtGui import QImage, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLabel, QComboBox, QSizePolicy, QInputDialog,
    QMessageBox, QFrame, QApplication, QMenu
)

from core import database, api_client
from core.utils import encode_qimage_to_base64


class ChatQueryWorker(QThread):
    """Background worker for AI chat streaming."""
    chunk_ready = QSignal(str)
    result_ready = QSignal(str)

    def __init__(self, messages: list, provider: dict):
        super().__init__()
        self.messages = messages
        self.provider = provider
        self.streaming = bool(provider.get("streaming", True))

    def run(self):
        full_text = ""
        try:
            if self.streaming:
                for chunk in api_client.explain_chat_stream(
                    self.messages,
                    self.provider["base_url"],
                    self.provider["api_key"],
                    self.provider["model"],
                    self.provider.get("proxy", ""),
                    float(self.provider.get("temperature", 0.7)),
                    int(self.provider.get("max_tokens", 4096)),
                ):
                    if chunk.startswith("Error:"):
                        self.result_ready.emit(chunk)
                        return
                    full_text += chunk
                    self.chunk_ready.emit(chunk)
                self.result_ready.emit(full_text)
            else:
                result = api_client.explain_chat(
                    self.messages,
                    self.provider["base_url"],
                    self.provider["api_key"],
                    self.provider["model"],
                    self.provider.get("proxy", ""),
                    float(self.provider.get("temperature", 0.7)),
                    int(self.provider.get("max_tokens", 4096)),
                )
                if result.startswith("Error:"):
                    self.result_ready.emit(result)
                    return
                self.chunk_ready.emit(result)
                self.result_ready.emit(result)
        except Exception as e:
            self.result_ready.emit(f"Error: {str(e)}")


class AiChatPanel(QWidget):
    """
    General-purpose AI chat panel with named persistent sessions.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.messages = []          # conversation history for current session
        self.current_session_id = None
        self.current_image_b64 = None
        self.current_image_mime = None
        self._worker = None
        self._stream_buffer = ""
        self._current_provider = None

        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Row 1: Session selector + actions
        session_row = QHBoxLayout()
        self.cmb_session = QComboBox()
        self.cmb_session.setMinimumWidth(100)
        self.cmb_session.currentIndexChanged.connect(self._on_session_changed)
        self.cmb_session.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cmb_session.customContextMenuRequested.connect(self._show_session_context_menu)

        self.btn_new_session = QPushButton("➕")
        self.btn_new_session.setFixedWidth(40)
        self.btn_new_session.setToolTip("New session")
        self.btn_new_session.clicked.connect(self._on_new_session)

        self.btn_delete_session = QPushButton("✕")
        self.btn_delete_session.setFixedWidth(40)
        self.btn_delete_session.setToolTip("Delete session")
        self.btn_delete_session.setStyleSheet("color: #cc4444; font-weight: bold;")
        self.btn_delete_session.clicked.connect(self._on_delete_session)

        session_row.addWidget(QLabel("Session:"))
        session_row.addWidget(self.cmb_session, 1)
        session_row.addWidget(self.btn_new_session)
        session_row.addWidget(self.btn_delete_session)
        layout.addLayout(session_row)

        # Row 2: Provider selector + token counter
        provider_row = QHBoxLayout()
        self.cmb_provider = QComboBox()
        self.cmb_provider.setMinimumWidth(120)
        self.cmb_provider.currentIndexChanged.connect(self._on_provider_changed)

        self.lbl_tokens = QLabel("Tokens: ~0")
        self.lbl_tokens.setStyleSheet("font-size: 11px; color: #888888;")

        provider_row.addWidget(QLabel("Provider:"))
        provider_row.addWidget(self.cmb_provider, 1)
        provider_row.addWidget(self.lbl_tokens)
        layout.addLayout(provider_row)

        # Chat display (capped height so input sits in lower-mid area)
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setPlaceholderText("Start a conversation...")
        self.chat_display.setMaximumHeight(480)
        self.chat_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.chat_display)

        # Image preview frame
        self.img_preview_frame = QFrame()
        self.img_preview_frame.setFrameShape(QFrame.Shape.StyledPanel)
        img_layout = QHBoxLayout(self.img_preview_frame)
        img_layout.setContentsMargins(4, 4, 4, 4)
        self.lbl_img_preview = QLabel("Drop or paste an image")
        self.lbl_img_preview.setFixedHeight(60)
        self.lbl_img_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_clear_img = QPushButton("✕")
        self.btn_clear_img.setFixedSize(24, 24)
        self.btn_clear_img.setToolTip("Remove image")
        self.btn_clear_img.clicked.connect(self._on_clear_image)
        self.btn_clear_img.hide()
        img_layout.addWidget(self.lbl_img_preview, 1)
        img_layout.addWidget(self.btn_clear_img)
        self.img_preview_frame.hide()
        layout.addWidget(self.img_preview_frame)

        # Input area — QTextEdit for multi-line with Shift+Enter
        input_layout = QHBoxLayout()
        self.edit_input = QTextEdit()
        self.edit_input.setPlaceholderText("Type a message... (Enter to send, Shift+Enter for new line)")
        self.edit_input.setMaximumHeight(80)
        self.edit_input.installEventFilter(self)

        self.btn_send = QPushButton("Send")
        self.btn_send.setFixedWidth(60)
        self.btn_send.clicked.connect(self._on_send)

        input_layout.addWidget(self.edit_input, 1)
        input_layout.addWidget(self.btn_send)
        layout.addLayout(input_layout)

        self._refresh_providers()
        self._refresh_sessions()

    # ------------------------------------------------------------------ #
    #  Event filter (Enter=send, Shift+Enter=newline, Ctrl+V paste image)
    # ------------------------------------------------------------------ #
    def eventFilter(self, obj, event):
        if obj == self.edit_input and event.type() == QEvent.Type.KeyPress:
            # Enter sends (unless Shift is held)
            if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
                if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    self._on_send()
                    return True
            # Ctrl+V paste image
            if event.key() == Qt.Key.Key_V and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                clipboard = QApplication.clipboard()
                mime = clipboard.mimeData()
                if mime.hasImage():
                    image = clipboard.image()
                    if not image.isNull():
                        self._load_image_from_qimage(image)
                        return True
                elif mime.hasUrls():
                    for url in mime.urls():
                        path = url.toLocalFile()
                        if path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp')):
                            self._load_image(path)
                            return True
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasImage():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                path = url.toLocalFile()
                if path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp')):
                    self._load_image(path)
                    event.acceptProposedAction()
                    return
        elif mime.hasImage():
            image = QImage(mime.imageData())
            if not image.isNull():
                self._load_image_from_qimage(image)
                event.acceptProposedAction()
                return
        event.ignore()

    # ------------------------------------------------------------------ #
    #  Session context menu
    # ------------------------------------------------------------------ #
    def _show_session_context_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("New Session").triggered.connect(self._on_new_session)
        if self.current_session_id is not None:
            menu.addAction("Rename").triggered.connect(self._on_rename_session)
        menu.exec(self.cmb_session.mapToGlobal(pos))

    # ------------------------------------------------------------------ #
    #  Sessions
    # ------------------------------------------------------------------ #
    def _refresh_sessions(self):
        self.cmb_session.blockSignals(True)
        self.cmb_session.clear()
        sessions = database.get_all_chat_sessions()
        if not sessions:
            sid = database.create_chat_session("New Chat")
            sessions = database.get_all_chat_sessions()
        for s in sessions:
            self.cmb_session.addItem(s["name"], s["id"])
        # Restore selection if possible
        if self.current_session_id is not None:
            idx = self.cmb_session.findData(self.current_session_id)
            if idx >= 0:
                self.cmb_session.setCurrentIndex(idx)
            elif self.cmb_session.count() > 0:
                self.cmb_session.setCurrentIndex(0)
        elif self.cmb_session.count() > 0:
            self.cmb_session.setCurrentIndex(0)
        self.cmb_session.blockSignals(False)
        self._on_session_changed(self.cmb_session.currentIndex())

    def _on_session_changed(self, index: int):
        if index < 0:
            return
        new_id = self.cmb_session.itemData(index)
        if new_id == self.current_session_id:
            return
        self._save_current_session()
        self.load_session(new_id)

    def load_session(self, session_id: int):
        self.current_session_id = session_id
        session = database.get_chat_session(session_id)
        if session:
            try:
                self.messages = json.loads(session.get("messages_json", "[]"))
            except Exception:
                self.messages = []
            self._rebuild_chat_display()
        else:
            self.messages = []
            self.chat_display.clear()
        self._update_token_label()

    def _save_current_session(self):
        if self.current_session_id is None:
            return
        database.update_chat_session(
            self.current_session_id,
            messages_json=json.dumps(self.messages, ensure_ascii=False),
            token_count=self._compute_token_count()
        )

    def _on_new_session(self):
        name, ok = QInputDialog.getText(self, "New Session", "Session name:")
        if ok and name.strip():
            sid = database.create_chat_session(name.strip())
            self._refresh_sessions()
            idx = self.cmb_session.findData(sid)
            if idx >= 0:
                self.cmb_session.setCurrentIndex(idx)

    def _on_rename_session(self):
        if self.current_session_id is None:
            return
        current_name = self.cmb_session.currentText()
        name, ok = QInputDialog.getText(self, "Rename Session", "New name:", text=current_name)
        if ok and name.strip():
            database.update_chat_session(self.current_session_id, name=name.strip())
            self._refresh_sessions()
            idx = self.cmb_session.findData(self.current_session_id)
            if idx >= 0:
                self.cmb_session.setCurrentIndex(idx)

    def _on_delete_session(self):
        if self.current_session_id is None:
            return
        reply = QMessageBox.question(
            self, "Delete Session",
            f"Delete session '{self.cmb_session.currentText()}'?\nThis cannot be undone."
        )
        if reply == QMessageBox.StandardButton.Yes:
            database.delete_chat_session(self.current_session_id)
            self.current_session_id = None
            self.messages = []
            self.chat_display.clear()
            self._update_token_label()
            self._refresh_sessions()

    # ------------------------------------------------------------------ #
    #  Provider
    # ------------------------------------------------------------------ #
    def _refresh_providers(self):
        self.cmb_provider.clear()
        providers = database.get_all_ai_providers()
        default_id = None
        for p in providers:
            display = f"{p['name']} {'(default)' if p.get('is_default') else ''}"
            self.cmb_provider.addItem(display, p["id"])
            if p.get("is_default"):
                default_id = p["id"]
        if default_id is not None:
            idx = self.cmb_provider.findData(default_id)
            if idx >= 0:
                self.cmb_provider.setCurrentIndex(idx)
        self._on_provider_changed(self.cmb_provider.currentIndex())

    def _on_provider_changed(self, index: int):
        if index < 0:
            self._current_provider = None
            return
        provider_id = self.cmb_provider.itemData(index)
        self._current_provider = database.get_ai_provider(provider_id)

    # ------------------------------------------------------------------ #
    #  Image handling
    # ------------------------------------------------------------------ #
    def _load_image(self, path: str):
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "Error", "Failed to load image.")
            return
        self._load_image_from_qimage(img)

    def _load_image_from_qimage(self, img: QImage):
        b64, mime = encode_qimage_to_base64(img, max_size=1024, quality=85)
        self.current_image_b64 = b64
        self.current_image_mime = mime
        # Thumbnail
        thumb = img.scaled(
            120, 60,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        thumb_ba = QByteArray()
        thumb_buffer = QBuffer(thumb_ba)
        thumb_buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        thumb.save(thumb_buffer, "PNG")
        pixmap = QPixmap()
        pixmap.loadFromData(thumb_ba.data())
        self.lbl_img_preview.setPixmap(pixmap)
        self.lbl_img_preview.setText("")
        self.btn_clear_img.show()
        self.img_preview_frame.show()

    def _on_clear_image(self):
        self.current_image_b64 = None
        self.current_image_mime = None
        self.lbl_img_preview.setPixmap(QPixmap())
        self.lbl_img_preview.setText("Drop or paste an image")
        self.btn_clear_img.hide()
        self.img_preview_frame.hide()

    # ------------------------------------------------------------------ #
    #  Send / receive
    # ------------------------------------------------------------------ #
    def _on_send(self):
        text = self.edit_input.toPlainText().strip()
        if not text and not self.current_image_b64:
            return
        if not self._current_provider:
            QMessageBox.warning(self, "Warning", "No AI provider selected.")
            return
        if not self._current_provider.get("api_key"):
            QMessageBox.warning(self, "Warning", "API Key not configured for the selected provider.")
            return

        self.edit_input.clear()

        if self.current_image_b64:
            content = [
                {"type": "text", "text": text or "What's in this image?"},
                {"type": "image_url", "image_url": {
                    "url": f"data:{self.current_image_mime};base64,{self.current_image_b64}"
                }}
            ]
        else:
            content = text

        self.messages.append({"role": "user", "content": content})
        self._rebuild_chat_display()
        self._on_clear_image()
        self._save_current_session()

        self._stream_buffer = ""
        self._start_worker()

    def _start_worker(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self._worker = ChatQueryWorker(self.messages.copy(), self._current_provider)
        self._worker.chunk_ready.connect(self._on_chunk)
        self._worker.result_ready.connect(self._on_result)
        self._worker.finished.connect(self._cleanup_worker)
        self._worker.start()

    def _on_chunk(self, chunk: str):
        if not self._stream_buffer:
            scrollbar = self.chat_display.verticalScrollBar()
            old_value = scrollbar.value()
            cursor = QTextCursor(self.chat_display.document())
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText("\n\n**AI:** ")
            scrollbar.setValue(old_value)
        self._stream_buffer += chunk
        scrollbar = self.chat_display.verticalScrollBar()
        old_value = scrollbar.value()
        cursor = QTextCursor(self.chat_display.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(chunk)
        scrollbar.setValue(old_value)

    def _on_result(self, result: str):
        if result.startswith("Error:"):
            if not self._stream_buffer:
                scrollbar = self.chat_display.verticalScrollBar()
                old_value = scrollbar.value()
                cursor = QTextCursor(self.chat_display.document())
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.insertText(f"\n\n*Error: {result[6:].strip()}*")
                scrollbar.setValue(old_value)
        else:
            self.messages.append({"role": "assistant", "content": result})
            self._rebuild_chat_display()
        self._stream_buffer = ""
        self._update_token_label()
        self._save_current_session()

    def _cleanup_worker(self):
        self._worker = None

    # ------------------------------------------------------------------ #
    #  Display & tokens
    # ------------------------------------------------------------------ #
    def _rebuild_chat_display(self):
        parts = []
        for msg in self.messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                continue
            if role == "user":
                if isinstance(content, list):
                    text_parts = []
                    has_image = False
                    for part in content:
                        if part.get("type") == "text":
                            text_parts.append(part["text"])
                        elif part.get("type") == "image_url":
                            has_image = True
                    display = " ".join(text_parts)
                    if has_image:
                        display += " 🖼️"
                    parts.append(f"**You:** {display}")
                else:
                    parts.append(f"**You:** {content}")
            elif role == "assistant":
                parts.append(f"**AI:** {content}")

        text = "\n\n".join(parts)
        scrollbar = self.chat_display.verticalScrollBar()
        old_value = scrollbar.value()
        self.chat_display.setMarkdown(text)
        scrollbar.setValue(old_value)

    def _compute_token_count(self) -> int:
        total = 0
        for msg in self.messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                for part in content:
                    if part.get("type") == "text":
                        total += database.estimate_tokens(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        total += 1000
            else:
                total += database.estimate_tokens(str(content))
        return total

    def _update_token_label(self):
        self.lbl_tokens.setText(f"Tokens: ~{self._compute_token_count()}")
