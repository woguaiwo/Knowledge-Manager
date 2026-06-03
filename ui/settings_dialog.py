"""
Settings dialog for configuring AI API parameters and theme.
Supports multiple AI providers.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QPushButton,
    QHBoxLayout, QMessageBox, QComboBox, QLabel, QSlider,
    QListWidget, QListWidgetItem, QAbstractItemView, QInputDialog,
    QCheckBox
)
from PySide6.QtCore import Qt

from core import database
from ui.theme_manager import THEMES


class ProviderEditDialog(QDialog):
    """Sub-dialog for adding or editing a single AI provider."""

    def __init__(self, provider: dict = None, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.setWindowTitle("Edit AI Provider" if provider else "Add AI Provider")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("e.g. OpenAI / DeepSeek / Kimi")
        form.addRow("Name:", self.edit_name)

        self.edit_base_url = QLineEdit()
        self.edit_base_url.setPlaceholderText("https://api.openai.com")
        form.addRow("API Base URL:", self.edit_base_url)

        self.edit_key = QLineEdit()
        self.edit_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_key.setPlaceholderText("sk-...")
        form.addRow("API Key:", self.edit_key)

        self.edit_model = QLineEdit()
        self.edit_model.setPlaceholderText("gpt-4o-mini")
        form.addRow("Model:", self.edit_model)

        self.edit_proxy = QLineEdit()
        self.edit_proxy.setPlaceholderText("http://127.0.0.1:7890 (optional)")
        form.addRow("Proxy:", self.edit_proxy)

        self.chk_streaming = QCheckBox("Streaming / 流式输出")
        self.chk_streaming.setChecked(True)
        form.addRow(self.chk_streaming)

        # Temperature slider (0.0 - 2.0, step 0.1)
        self.slider_temp = QSlider(Qt.Orientation.Horizontal)
        self.slider_temp.setMinimum(0)
        self.slider_temp.setMaximum(20)
        self.slider_temp.setTickInterval(5)
        self.slider_temp.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.lbl_temp = QLabel("0.7")
        self.slider_temp.valueChanged.connect(lambda v: self.lbl_temp.setText(f"{v / 10:.1f}"))
        temp_layout = QHBoxLayout()
        temp_layout.addWidget(self.slider_temp)
        temp_layout.addWidget(self.lbl_temp)
        form.addRow("Temperature:", temp_layout)

        self.edit_max_tokens = QLineEdit()
        self.edit_max_tokens.setPlaceholderText("4096")
        form.addRow("Max Tokens:", self.edit_max_tokens)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("Save")
        self.btn_cancel = QPushButton("Cancel")
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        self.btn_save.clicked.connect(self._save)
        self.btn_cancel.clicked.connect(self.reject)

        if provider:
            self.edit_name.setText(provider.get("name", ""))
            self.edit_base_url.setText(provider.get("base_url", ""))
            self.edit_key.setText(provider.get("api_key", ""))
            self.edit_model.setText(provider.get("model", ""))
            self.edit_proxy.setText(provider.get("proxy", ""))
            self.chk_streaming.setChecked(bool(provider.get("streaming", True)))
            temp_val = int(float(provider.get("temperature", 0.7)) * 10)
            self.slider_temp.setValue(temp_val)
            self.lbl_temp.setText(f"{temp_val / 10:.1f}")
            self.edit_max_tokens.setText(str(provider.get("max_tokens", 4096)))

    def _save(self):
        name = self.edit_name.text().strip()
        base_url = self.edit_base_url.text().strip()
        api_key = self.edit_key.text().strip()
        model = self.edit_model.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Provider name is required.")
            return
        if not base_url:
            QMessageBox.warning(self, "Validation", "API Base URL is required.")
            return
        if not api_key:
            QMessageBox.warning(self, "Validation", "API Key is required.")
            return
        if not model:
            QMessageBox.warning(self, "Validation", "Model is required.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "name": self.edit_name.text().strip(),
            "base_url": self.edit_base_url.text().strip(),
            "api_key": self.edit_key.text().strip(),
            "model": self.edit_model.text().strip(),
            "proxy": self.edit_proxy.text().strip(),
            "streaming": self.chk_streaming.isChecked(),
            "temperature": self.slider_temp.value() / 10,
            "max_tokens": int(self.edit_max_tokens.text().strip() or 4096),
        }


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)
        self.setMinimumHeight(500)

        layout = QVBoxLayout(self)

        # --- Theme & Mask ---
        form = QFormLayout()

        self.combo_theme = QComboBox()
        for key, meta in THEMES.items():
            self.combo_theme.addItem(meta["name"], key)
        form.addRow("Theme:", self.combo_theme)

        self.slider_mask = QSlider(Qt.Orientation.Horizontal)
        self.slider_mask.setMinimum(0)
        self.slider_mask.setMaximum(100)
        self.slider_mask.setTickInterval(10)
        self.slider_mask.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.lbl_mask = QLabel("35%")
        self.slider_mask.valueChanged.connect(lambda v: self.lbl_mask.setText(f"{v}%"))
        mask_layout = QHBoxLayout()
        mask_layout.addWidget(self.slider_mask)
        mask_layout.addWidget(self.lbl_mask)
        form.addRow("Mask Amount:", mask_layout)

        # Temperature slider (0.0 - 2.0, step 0.1)
        layout.addLayout(form)
        layout.addSpacing(10)

        # --- AI Providers ---
        layout.addWidget(QLabel("🤖 AI Providers"))
        layout.addWidget(QLabel("Double-click to edit. Select one as default."))

        self.provider_list = QListWidget()
        self.provider_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.provider_list.itemDoubleClicked.connect(self._edit_provider)
        layout.addWidget(self.provider_list)

        provider_btn_layout = QHBoxLayout()
        self.btn_add_provider = QPushButton("➕ Add")
        self.btn_edit_provider = QPushButton("✏️ Edit")
        self.btn_del_provider = QPushButton("🗑 Delete")
        self.btn_set_default = QPushButton("⭐ Set Default")
        provider_btn_layout.addWidget(self.btn_add_provider)
        provider_btn_layout.addWidget(self.btn_edit_provider)
        provider_btn_layout.addWidget(self.btn_del_provider)
        provider_btn_layout.addWidget(self.btn_set_default)
        provider_btn_layout.addStretch()
        layout.addLayout(provider_btn_layout)

        self.btn_add_provider.clicked.connect(self._add_provider)
        self.btn_edit_provider.clicked.connect(self._edit_provider)
        self.btn_del_provider.clicked.connect(self._del_provider)
        self.btn_set_default.clicked.connect(self._set_default_provider)

        layout.addSpacing(10)

        # --- Bottom buttons ---
        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("Save All")
        self.btn_cancel = QPushButton("Cancel")
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        self.btn_save.clicked.connect(self._save)
        self.btn_cancel.clicked.connect(self.reject)

        self._load()
        self.setLayout(layout)

    def _load(self):
        current_theme = database.get_setting("theme", "dark")
        idx = self.combo_theme.findData(current_theme)
        if idx >= 0:
            self.combo_theme.setCurrentIndex(idx)
        mask_val = int(float(database.get_setting("mask_ratio", "35")))
        self.slider_mask.setValue(mask_val)
        self.lbl_mask.setText(f"{mask_val}%")



        # Load providers
        self._providers = database.get_all_ai_providers()
        self._refresh_provider_list()

        # Migrate old single-provider settings if no providers exist yet
        if not self._providers:
            old_url = database.get_setting("api_base_url", "")
            old_key = database.get_setting("api_key", "")
            old_model = database.get_setting("api_model", "")
            if old_url or old_key or old_model:
                default_provider = {
                    "name": "Default",
                    "base_url": old_url or "https://api.openai.com",
                    "api_key": old_key or "",
                    "model": old_model or "gpt-4o-mini",
                    "proxy": database.get_setting("api_proxy", ""),
                }
                pid = database.add_ai_provider(
                    default_provider["name"],
                    default_provider["base_url"],
                    default_provider["api_key"],
                    default_provider["model"],
                    default_provider["proxy"],
                    is_default=True,
                )
                default_provider["id"] = pid
                default_provider["is_default"] = 1
                self._providers = [default_provider]
                self._refresh_provider_list()

    def _refresh_provider_list(self):
        self.provider_list.clear()
        for p in self._providers:
            item = QListWidgetItem()
            default_mark = " ⭐" if p.get("is_default") else ""
            stream_mark = " 🌊" if p.get("streaming", True) else ""
            item.setText(f"{p['name']} ({p['model']}){stream_mark}{default_mark}")
            item.setData(Qt.ItemDataRole.UserRole, p["id"])
            self.provider_list.addItem(item)

    def _add_provider(self):
        dlg = ProviderEditDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            is_default = len(self._providers) == 0
            pid = database.add_ai_provider(
                data["name"], data["base_url"], data["api_key"],
                data["model"], data["proxy"], is_default,
                streaming=data.get("streaming", True),
                temperature=data.get("temperature", 0.7),
                max_tokens=data.get("max_tokens", 4096)
            )
            self._providers = database.get_all_ai_providers()
            self._refresh_provider_list()
            # Select the newly added item
            for i in range(self.provider_list.count()):
                if self.provider_list.item(i).data(Qt.ItemDataRole.UserRole) == pid:
                    self.provider_list.setCurrentRow(i)
                    break

    def _edit_provider(self):
        item = self.provider_list.currentItem()
        if not item:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        provider = database.get_ai_provider(pid)
        if not provider:
            return
        dlg = ProviderEditDialog(provider, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            database.update_ai_provider(
                pid, name=data["name"], base_url=data["base_url"],
                api_key=data["api_key"], model=data["model"], proxy=data["proxy"],
                streaming=data.get("streaming", True),
                temperature=data.get("temperature", 0.7),
                max_tokens=data.get("max_tokens", 4096)
            )
            self._providers = database.get_all_ai_providers()
            self._refresh_provider_list()

    def _del_provider(self):
        item = self.provider_list.currentItem()
        if not item:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "Confirm", "Delete this AI provider?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            database.delete_ai_provider(pid)
            self._providers = database.get_all_ai_providers()
            self._refresh_provider_list()

    def _set_default_provider(self):
        item = self.provider_list.currentItem()
        if not item:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        database.update_ai_provider(pid, is_default=True)
        self._providers = database.get_all_ai_providers()
        self._refresh_provider_list()

    def _save(self):
        database.save_setting("theme", self.combo_theme.currentData())
        database.save_setting("mask_ratio", str(self.slider_mask.value()))

        QMessageBox.information(self, "Saved", "Settings saved successfully.")
        self.accept()
