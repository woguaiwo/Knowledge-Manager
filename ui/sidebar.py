"""
Collapsible sidebar that hosts the Explorer tree and other tool views.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QSizePolicy

from ui.explorer_tree import ExplorerTree


class Sidebar(QWidget):
    """
    Sidebar widget that shows different content based on the active tool.
    Currently supports: Explorer (folder tree).
    """
    file_selected = Signal(str)  # PDF file chosen in explorer
    open_folder_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(250)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Header
        header = QLabel("📁 Explorer")
        header.setStyleSheet("font-size: 14px; font-weight: bold; padding: 4px;")
        layout.addWidget(header)

        # Open Folder button
        self.btn_open_folder = QPushButton("Open Folder")
        self.btn_open_folder.clicked.connect(self.open_folder_requested.emit)
        layout.addWidget(self.btn_open_folder)

        # Tree view
        self.tree = ExplorerTree(self)
        self.tree.file_selected.connect(self.file_selected.emit)
        layout.addWidget(self.tree)

        self.setLayout(layout)

    def set_root_folder(self, path: str):
        self.tree.set_root(path)
