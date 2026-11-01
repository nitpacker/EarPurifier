from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QProgressBar, QFrame, QDialog, QHBoxLayout
)
from PySide6.QtCore import Qt

from .theme import Theme, FONT_FAMILY
from .components import RotatingSpinner
from i18n import t, translate_worker_message


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

        self.spinner = RotatingSpinner(18)
        self.spinner.hide()
        self._raw_status = ""
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #557364; font-size: 11px; border: none; background: transparent;")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setVisible(False)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(8)
        status_row.setAlignment(Qt.AlignCenter)
        status_row.addWidget(self.spinner)
        status_row.addWidget(self.lbl_status)
        card_layout.addLayout(status_row)

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
        self.progress.setRange(0, 0)
        self.spinner.start()
        self.lbl_status.setVisible(True)
        self.lbl_status.setStyleSheet("color: #557364; font-size: 11px; border: none; background: transparent;")

    def set_status_message(self, text: str):
        self._raw_status = text
        self.lbl_status.setText(translate_worker_message(text))

    def set_error(self, err_msg: str):
        self.spinner.stop()
        self.btn_download.setEnabled(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.lbl_status.setText(err_msg)
        self.lbl_status.setStyleSheet("color: #ef4444; font-size: 11px; border: none; background: transparent;")

    def hideEvent(self, event):
        self.spinner.stop()
        super().hideEvent(event)


class CloseActiveJobDialog(QDialog):
    """Studio confirmation dialog shown when closing while a job is actively processing."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("close_active_job_title"))
        self.setMinimumWidth(440)
        self.setMaximumWidth(500)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        mode = Theme.get_mode()
        card_bg = Theme.get_token("CARD_BG", mode)
        card_border = Theme.get_token("CARD_BORDER", mode)
        text_head = Theme.get_token("TEXT_HEAD", mode)
        text_body = Theme.get_token("TEXT_BODY", mode)
        meta_bg = Theme.get_token("META_BG", mode)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {card_bg};
                border-radius: 12px;
            }}
            QLabel {{
                background: transparent;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        lbl_title = QLabel(t("close_active_job_title"))
        lbl_title.setStyleSheet(f"font-size: 15px; font-weight: 800; color: {text_head};")
        layout.addWidget(lbl_title)

        lbl_msg = QLabel(t("close_active_job_msg"))
        lbl_msg.setWordWrap(True)
        lbl_msg.setStyleSheet(f"font-size: 12px; color: {text_body}; line-height: 1.4;")
        layout.addWidget(lbl_msg)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        self.btn_keep = QPushButton(t("btn_keep_running"))
        self.btn_keep.setCursor(Qt.PointingHandCursor)
        self.btn_keep.setStyleSheet(f"""
            QPushButton {{
                background-color: {meta_bg};
                color: {text_head};
                border: 1px solid {card_border};
                padding: 8px 18px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 12px;
            }}
            QPushButton:hover {{
                border-color: {Theme.get_token('ACCENT_EMERALD')};
            }}
        """)
        self.btn_keep.clicked.connect(self.reject)
        self.btn_keep.setDefault(True)

        self.btn_abort = QPushButton(t("btn_close_and_abort"))
        self.btn_abort.setCursor(Qt.PointingHandCursor)
        self.btn_abort.setStyleSheet("""
            QPushButton {{
                background-color: #ef4444;
                color: #ffffff;
                font-weight: 700;
                padding: 8px 18px;
                border-radius: 6px;
                border: none;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: #dc2626;
            }}
        """)
        self.btn_abort.clicked.connect(self.accept)

        btn_layout.addWidget(self.btn_keep)
        btn_layout.addWidget(self.btn_abort)
        layout.addLayout(btn_layout)

