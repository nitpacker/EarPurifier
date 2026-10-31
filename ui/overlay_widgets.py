from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QProgressBar, QFrame
)
from PySide6.QtCore import Qt

from .theme import Theme, FONT_FAMILY


class DownloadOverlayWidget(QWidget):
    """Clean frosted backdrop overlay with elevated card for dependency downloads."""
    def __init__(self, title_text: str, desc_text: str, btn_text: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: rgba(244, 248, 245, 235);")

        overlay_layout = QVBoxLayout(self)
        overlay_layout.setAlignment(Qt.AlignCenter)

        self.card = QFrame()
        self.card.setObjectName("warningBox")
        self.card.setMinimumWidth(440)
        self.card.setMaximumWidth(520)
        self.card.setStyleSheet(f"""
            QFrame#warningBox {{
                background-color: #ffffff;
                border: 1px solid #dfebe4;
                border-radius: 12px;
            }}
        """)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(24, 22, 24, 22)
        card_layout.setSpacing(10)

        self.lbl_title = QLabel(title_text)
        self.lbl_title.setStyleSheet("font-size: 16px; font-weight: 800; color: #0b2318; border: none; background: transparent;")
        self.lbl_title.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(self.lbl_title)

        self.lbl_desc = QLabel(desc_text)
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet("font-size: 12px; color: #557364; border: none; background: transparent;")
        self.lbl_desc.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(self.lbl_desc)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        card_layout.addWidget(self.progress)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #557364; font-size: 11px; border: none; background: transparent;")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setVisible(False)
        card_layout.addWidget(self.lbl_status)

        self.btn_download = QPushButton(btn_text)
        self.btn_download.setCursor(Qt.PointingHandCursor)
        self.btn_download.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #0d9488);
                color: #ffffff;
                font-weight: 700;
                font-size: 12.5px;
                border-radius: 6px;
                padding: 9px;
                border: none;
            }
            QPushButton:hover { background-color: #047857; }
            QPushButton:disabled { background-color: #a7f3d0; }
        """)
        card_layout.addWidget(self.btn_download)

        overlay_layout.addWidget(self.card)

    def set_downloading(self):
        self.btn_download.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.lbl_status.setVisible(True)

    def set_error(self, err_msg: str):
        self.btn_download.setEnabled(True)
        self.lbl_status.setText(err_msg)
        self.lbl_status.setStyleSheet("color: #ef4444; font-size: 11px;")
