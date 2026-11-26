from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QProgressBar, QFrame, QDialog, QHBoxLayout
)
from PySide6.QtCore import Qt, QTimer, Signal

from .theme import Theme, FONT_FAMILY, get_primary_button_qss
from .components import RotatingSpinner, CleanCloseButton, VectorWarningBadge
from i18n import t, translate_worker_message, get_current_language, is_rtl


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

    def set_progress(self, pct: int):
        pct = max(0, min(100, int(pct)))
        if pct > 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(pct)

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


class VerificationReminderBanner(QFrame):
    """
    Non-invasive notification banner that appears at the top of the canvas
    when Kaggle GPU accelerator quota cannot be verified or times out.
    Automatically closes after 20 seconds.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("verificationBanner")
        self._theme_mode = Theme.get_mode()
        self._model_name = ""

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

        self.init_ui()
        self.apply_theme(self._theme_mode)
        self.setVisible(False)

    def init_ui(self):
        current_lang = get_current_language()
        direction = Qt.RightToLeft if is_rtl(current_lang) else Qt.LeftToRight
        self.setLayoutDirection(direction)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        # Warning icon indicator
        self.icon_badge = VectorWarningBadge(size=32, parent=self)
        layout.addWidget(self.icon_badge, 0, Qt.AlignVCenter)

        # Content layout (Title + Message)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        text_layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_title = QLabel(self)
        self.lbl_title.setStyleSheet("font-size: 13px; font-weight: 800; background: transparent;")
        text_layout.addWidget(self.lbl_title)

        self.lbl_msg = QLabel(self)
        self.lbl_msg.setWordWrap(True)
        self.lbl_msg.setStyleSheet("font-size: 11.5px; background: transparent;")
        text_layout.addWidget(self.lbl_msg)

        layout.addLayout(text_layout, 1)

        # Dismiss button
        self.btn_close = CleanCloseButton(self)
        self.btn_close.clicked.connect(self.dismiss)
        layout.addWidget(self.btn_close, 0, Qt.AlignVCenter)

    def show_reminder(self, model_name: str):
        self._model_name = model_name
        current_lang = get_current_language()
        self.setLayoutDirection(Qt.RightToLeft if is_rtl(current_lang) else Qt.LeftToRight)
        self.lbl_title.setText(t("phone_reminder_title"))
        self.lbl_msg.setText(t("phone_reminder_msg", model=model_name))
        self.apply_theme(Theme.get_mode())
        self.setVisible(True)

        self._timer.stop()
        self._timer.start(20000)

    def dismiss(self):
        if self._timer and self._timer.isActive():
            self._timer.stop()
        self.setVisible(False)

    def apply_theme(self, mode: str):
        self._theme_mode = mode
        card_bg = Theme.get_token("CARD_BG", mode)
        text_head = Theme.get_token("TEXT_HEAD", mode)
        text_body = Theme.get_token("TEXT_BODY", mode)

        self.setStyleSheet(f"""
            QFrame#verificationBanner {{
                background-color: {card_bg};
                border: 1px solid #f59e0b;
                border-radius: 10px;
                margin: 6px 12px 0px 12px;
            }}
        """)
        self.lbl_title.setStyleSheet(f"font-size: 13px; font-weight: 800; color: {text_head}; background: transparent;")
        self.lbl_msg.setStyleSheet(f"font-size: 11.5px; color: {text_body}; background: transparent;")

    def retranslate_ui(self, lang: str):
        self.setLayoutDirection(Qt.RightToLeft if is_rtl(lang) else Qt.LeftToRight)
        if hasattr(self, 'btn_close'):
            self.btn_close.retranslate_ui()
        if self._model_name:
            self.lbl_title.setText(t("phone_reminder_title"))
            self.lbl_msg.setText(t("phone_reminder_msg", model=self._model_name))


class GpuUpgradeBanner(QFrame):
    """
    Non-blocking, dismissible banner shown in the Local tab when an NVIDIA GPU
    is detected on the host but the Local Engine is running a CPU-only PyTorch build.
    Supports inline upgrade progress, error retry, theme switching, and bilingual EN/AR.
    """
    upgrade_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("gpuUpgradeBanner")
        self._theme_mode = Theme.get_mode()
        self._state = "idle"  # "idle" | "upgrading" | "error"
        self._raw_status = ""
        self._error_text = ""

        self.init_ui()
        self.apply_theme(self._theme_mode)
        self.setVisible(False)

    def init_ui(self):
        current_lang = get_current_language()
        self.setLayoutDirection(Qt.RightToLeft if is_rtl(current_lang) else Qt.LeftToRight)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        text_layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_title = QLabel(t("gpu_banner_title"), self)
        text_layout.addWidget(self.lbl_title)

        self.lbl_msg = QLabel(t("gpu_banner_desc"), self)
        self.lbl_msg.setWordWrap(True)
        text_layout.addWidget(self.lbl_msg)

        top_row.addLayout(text_layout, 1)

        self.btn_upgrade = QPushButton(t("gpu_banner_btn_upgrade"), self)
        self.btn_upgrade.setCursor(Qt.PointingHandCursor)
        self.btn_upgrade.clicked.connect(self.upgrade_requested.emit)
        top_row.addWidget(self.btn_upgrade, 0, Qt.AlignVCenter)

        self.btn_close = CleanCloseButton(self)
        self.btn_close.clicked.connect(self.dismiss)
        top_row.addWidget(self.btn_close, 0, Qt.AlignVCenter)

        outer.addLayout(top_row)

        # Inline progress & status row (hidden until upgrade starts or fails)
        self.progress_container = QWidget(self)
        self.progress_container.setStyleSheet("background: transparent;")
        prog_layout = QVBoxLayout(self.progress_container)
        prog_layout.setContentsMargins(0, 2, 0, 0)
        prog_layout.setSpacing(4)

        self.progress = QProgressBar(self.progress_container)
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        prog_layout.addWidget(self.progress)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(6)

        self.spinner = RotatingSpinner(14)
        self.spinner.hide()
        status_row.addWidget(self.spinner)

        self.lbl_status = QLabel("", self.progress_container)
        self.lbl_status.setWordWrap(True)
        status_row.addWidget(self.lbl_status, 1)

        prog_layout.addLayout(status_row)
        self.progress_container.setVisible(False)
        outer.addWidget(self.progress_container)

    def set_upgrading(self):
        self._state = "upgrading"
        self._error_text = ""
        self.btn_upgrade.setEnabled(False)
        self.btn_close.setVisible(False)
        self.progress_container.setVisible(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.spinner.show()
        self.spinner.start()
        self._raw_status = ""
        self.lbl_status.setText(t("gpu_banner_upgrading"))
        text_muted = Theme.get_token("TEXT_MUTED", self._theme_mode)
        self.lbl_status.setStyleSheet(f"font-size: 11px; color: {text_muted}; background: transparent;")

    def set_progress(self, pct: int):
        pct = max(0, min(100, int(pct)))
        if pct > 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(pct)

    def set_status_message(self, text: str):
        self._raw_status = text
        self.lbl_status.setText(translate_worker_message(text))

    def set_error(self, err_msg: str, allow_dismiss: bool = True):
        self._state = "error"
        self._error_text = err_msg
        self.spinner.stop()
        self.spinner.hide()
        self.btn_upgrade.setEnabled(True)
        self.btn_upgrade.setText(t("gpu_banner_btn_retry"))
        self.btn_close.setVisible(allow_dismiss)
        self.progress_container.setVisible(True)
        self.progress.setVisible(False)
        self.lbl_status.setText(err_msg)
        self.lbl_status.setStyleSheet("font-size: 11px; color: #ef4444; background: transparent;")

    def reset_idle(self):
        self._state = "idle"
        self._error_text = ""
        self._raw_status = ""
        self.spinner.stop()
        self.spinner.hide()
        self.btn_upgrade.setEnabled(True)
        self.btn_upgrade.setText(t("gpu_banner_btn_upgrade"))
        self.btn_close.setVisible(True)
        self.progress_container.setVisible(False)

    def dismiss(self):
        if self._state == "upgrading":
            return
        self.spinner.stop()
        self.setVisible(False)

    def hideEvent(self, event):
        self.spinner.stop()
        super().hideEvent(event)

    def apply_theme(self, mode: str):
        self._theme_mode = mode
        card_bg = Theme.get_token("CARD_BG", mode)
        card_border = Theme.get_token("CARD_BORDER", mode)
        text_head = Theme.get_token("TEXT_HEAD", mode)
        text_body = Theme.get_token("TEXT_BODY", mode)
        text_muted = Theme.get_token("TEXT_MUTED", mode)
        accent_emerald = Theme.get_token("ACCENT_EMERALD", mode)
        accent_teal = Theme.get_token("ACCENT_TEAL", mode)

        self.setStyleSheet(f"""
            QFrame#gpuUpgradeBanner {{
                background-color: {card_bg};
                border: 1px solid {accent_emerald};
                border-radius: 10px;
                margin: 10px 20px 0px 20px;
            }}
        """)
        self.lbl_title.setStyleSheet(f"font-size: 13px; font-weight: 800; color: {text_head}; background: transparent;")
        self.lbl_msg.setStyleSheet(f"font-size: 11.5px; color: {text_body}; background: transparent;")
        self.btn_upgrade.setStyleSheet(get_primary_button_qss(mode))
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {card_border};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {accent_emerald}, stop:1 {accent_teal});
                border-radius: 3px;
            }}
        """)
        if self._state == "error":
            self.lbl_status.setStyleSheet("font-size: 11px; color: #ef4444; background: transparent;")
        else:
            self.lbl_status.setStyleSheet(f"font-size: 11px; color: {text_muted}; background: transparent;")

    def retranslate_ui(self, lang: str):
        self.setLayoutDirection(Qt.RightToLeft if is_rtl(lang) else Qt.LeftToRight)
        self.lbl_title.setText(t("gpu_banner_title"))
        self.lbl_msg.setText(t("gpu_banner_desc"))
        if self._state == "error":
            self.btn_upgrade.setText(t("gpu_banner_btn_retry"))
        else:
            self.btn_upgrade.setText(t("gpu_banner_btn_upgrade"))
        if self._state == "upgrading":
            if self._raw_status:
                self.lbl_status.setText(translate_worker_message(self._raw_status))
            else:
                self.lbl_status.setText(t("gpu_banner_upgrading"))
        if hasattr(self, "btn_close"):
            self.btn_close.retranslate_ui()


