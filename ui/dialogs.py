import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QFormLayout, QFrame,
    QFileDialog, QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices

from .theme import (
    Theme, ThemeMode,
    get_combobox_qss, get_checkbox_qss, get_primary_button_qss,
    FONT_FAMILY, FONT_MONO
)
from .components import VectorAlertBadge, ModernToggleSwitch

try:
    from config_manager import ConfigManager
except ImportError:
    from src.config_manager import ConfigManager

try:
    from i18n import t, is_rtl, format_delete_confirm_msg
except ImportError:
    from src.i18n import t, is_rtl, format_delete_confirm_msg

try:
    from update_checker import GitHubUpdateChecker
except ImportError:
    from src.update_checker import GitHubUpdateChecker


# ─── Settings Dialog (Modern Elevated Studio Cards) ───────────────────────────

class SettingsDialog(QDialog):
    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle(t("settings_window_title"))
        self.setMinimumWidth(500)
        self._theme_mode = Theme.get_mode()
        self.update_thread = None
        self._pending_download_url = ""
        self._update_is_download_ready = False

        current_lang = self.config.get("language", "ar")
        rtl_mode = is_rtl(current_lang)

        self.setLayoutDirection(Qt.RightToLeft if rtl_mode else Qt.LeftToRight)
        self.apply_dialog_style(rtl_mode)
        self.init_ui(current_lang)

    def apply_dialog_style(self, rtl_mode: bool):
        mode = self._theme_mode
        canvas_bg = Theme.get_token("CANVAS_BG", mode)
        card_bg = Theme.get_token("CARD_BG", mode)
        card_border = Theme.get_token("CARD_BORDER", mode)
        text_head = Theme.get_token("TEXT_HEAD", mode)
        text_body = Theme.get_token("TEXT_BODY", mode)
        meta_bg = Theme.get_token("META_BG", mode)
        accent = Theme.get_token("ACCENT_EMERALD", mode)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {canvas_bg};
            }}
            QLabel {{
                color: {text_body};
                font-size: 12px;
                font-weight: 600;
                background: transparent;
            }}
            QLineEdit {{
                background-color: {meta_bg};
                border: 1px solid {card_border};
                border-radius: 7px;
                padding: 7px 10px;
                color: {text_head};
                font-size: 12.5px;
            }}
            QLineEdit:focus {{
                border-color: {accent};
            }}
            QFrame#elevatedCard {{
                background-color: {card_bg};
                border: 1px solid {card_border};
                border-radius: 12px;
            }}
        """)

    def init_ui(self, current_lang: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 18, 20, 18)

        # Header Title
        title_box = QHBoxLayout()
        title_box.setSpacing(8)

        self.lbl_title = QLabel(t("settings_header"))
        self.lbl_title.setStyleSheet(f"font-size: 16px; font-weight: 800; color: {Theme.get_token('TEXT_HEAD')};")
        title_box.addWidget(self.lbl_title)
        title_box.addStretch()
        layout.addLayout(title_box)

        # ── Card 1: Kaggle Cloud Accelerator ──
        self.card_kaggle = QFrame()
        self.card_kaggle.setObjectName("elevatedCard")
        ck_layout = QVBoxLayout(self.card_kaggle)
        ck_layout.setContentsMargins(14, 12, 14, 12)
        ck_layout.setSpacing(10)

        lbl_k_head = QLabel(t("settings_grp_kaggle"))
        lbl_k_head.setStyleSheet(f"font-size: 12px; font-weight: 800; color: {Theme.get_token('ACCENT_EMERALD')};")
        ck_layout.addWidget(lbl_k_head)

        form_kaggle = QFormLayout()
        form_kaggle.setSpacing(8)

        self.inp_user = QLineEdit(self.config.get("kaggle_username"))
        self.inp_user.setPlaceholderText(t("settings_kaggle_user_ph"))
        self.inp_key = QLineEdit(self.config.get("kaggle_api_key"))
        self.inp_key.setEchoMode(QLineEdit.Password)
        self.inp_key.setPlaceholderText("••••••••••••••••")

        form_kaggle.addRow(t("settings_kaggle_user"), self.inp_user)
        form_kaggle.addRow(t("settings_kaggle_key"), self.inp_key)
        ck_layout.addLayout(form_kaggle)
        layout.addWidget(self.card_kaggle)

        # ── Card 2: General & Engine Settings ──
        self.card_general = QFrame()
        self.card_general.setObjectName("elevatedCard")
        cg_layout = QVBoxLayout(self.card_general)
        cg_layout.setContentsMargins(14, 12, 14, 12)
        cg_layout.setSpacing(10)

        lbl_g_head = QLabel(t("settings_grp_general"))
        lbl_g_head.setStyleSheet(f"font-size: 12px; font-weight: 800; color: {Theme.get_token('ACCENT_EMERALD')};")
        cg_layout.addWidget(lbl_g_head)

        form_general = QFormLayout()
        form_general.setSpacing(8)

        # Language Selector
        self.cmb_lang = QComboBox()
        self.cmb_lang.addItem("العربية", "ar")
        self.cmb_lang.addItem("English", "en")
        idx = 0 if current_lang == "ar" else 1
        self.cmb_lang.setCurrentIndex(idx)
        self.cmb_lang.setStyleSheet(get_combobox_qss(is_rtl(current_lang), self._theme_mode))
        form_general.addRow(t("settings_language"), self.cmb_lang)

        # Output Folder
        out_layout = QHBoxLayout()
        out_layout.setSpacing(6)
        self.inp_out = QLineEdit(self.config.get("output_folder"))
        self.inp_out.setPlaceholderText(t("settings_out_folder_ph"))
        self.btn_browse = QPushButton(t("settings_btn_browse"))
        self.btn_browse.setCursor(Qt.PointingHandCursor)
        self.btn_browse.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.get_token('CARD_BG')};
                color: {Theme.get_token('TEXT_BODY')};
                border: 1px solid {Theme.get_token('CARD_BORDER')};
                padding: 6px 12px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 11.5px;
            }}
            QPushButton:hover {{
                border-color: {Theme.get_token('ACCENT_EMERALD')};
            }}
        """)
        self.btn_browse.clicked.connect(self.browse_output)
        out_layout.addWidget(self.inp_out, 1)
        out_layout.addWidget(self.btn_browse)
        form_general.addRow(t("settings_out_folder"), out_layout)

        # Local AI Model
        self.cmb_model = QComboBox()
        self.cmb_model.addItems([
            "SOTA (RoFormer) - Requires High-End GPU",
            "Mid (MDX23C) - Balanced Quality & Speed",
            "Low (MDXNET) - Fast & Low VRAM"
        ])
        self.cmb_model.setCurrentText(self.config.get("local_model"))
        self.cmb_model.setStyleSheet(get_combobox_qss(is_rtl(current_lang), self._theme_mode))
        form_general.addRow(t("settings_local_model"), self.cmb_model)

        # Modern iOS Toggle Switch for Logging
        log_row = QHBoxLayout()
        lbl_log = QLabel(t("settings_enable_logging"))
        self.switch_logging = ModernToggleSwitch(self.config.get("enable_logging", True))
        log_row.addWidget(lbl_log, 1)
        log_row.addWidget(self.switch_logging)
        form_general.addRow("", log_row)

        # Auto-Update Toggle Switch
        upd_row = QHBoxLayout()
        lbl_upd = QLabel(t("setting_check_updates"))
        self.switch_check_updates = ModernToggleSwitch(self.config.get("check_updates", True))
        upd_row.addWidget(lbl_upd, 1)
        upd_row.addWidget(self.switch_check_updates)
        form_general.addRow("", upd_row)

        # Manual Check Button & Inline Status
        chk_row = QHBoxLayout()
        chk_row.setSpacing(10)
        self.btn_check_now = QPushButton(t("btn_check_updates_now"))
        self.btn_check_now.setCursor(Qt.PointingHandCursor)
        self._apply_check_btn_style(is_download_mode=False)
        self.btn_check_now.clicked.connect(self.on_check_or_download_clicked)
        chk_row.addWidget(self.btn_check_now)

        self.lbl_update_status = QLabel("")
        self.lbl_update_status.setStyleSheet(f"color: {Theme.get_token('TEXT_MUTED')}; font-size: 11px;")
        chk_row.addWidget(self.lbl_update_status, 1)
        form_general.addRow("", chk_row)

        cg_layout.addLayout(form_general)
        layout.addWidget(self.card_general)

        # Save Button
        self.btn_save = QPushButton(t("settings_btn_save"))
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setStyleSheet(get_primary_button_qss(self._theme_mode))
        self.btn_save.clicked.connect(self.accept)
        layout.addWidget(self.btn_save)

    def _apply_check_btn_style(self, is_download_mode: bool = False):
        if is_download_mode:
            self.btn_check_now.setText(t("btn_download_update"))
            self.btn_check_now.setStyleSheet(get_primary_button_qss(self._theme_mode))
        else:
            self.btn_check_now.setText(t("btn_check_updates_now"))
            self.btn_check_now.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Theme.get_token('CARD_BG')};
                    color: {Theme.get_token('TEXT_BODY')};
                    border: 1px solid {Theme.get_token('CARD_BORDER')};
                    padding: 6px 14px;
                    border-radius: 6px;
                    font-weight: 600;
                    font-size: 11.5px;
                }}
                QPushButton:hover {{
                    border-color: {Theme.get_token('ACCENT_EMERALD')};
                }}
                QPushButton:disabled {{
                    color: {Theme.get_token('TEXT_FAINT')};
                }}
            """)

    def on_check_or_download_clicked(self):
        if self._update_is_download_ready and self._pending_download_url:
            QDesktopServices.openUrl(QUrl(self._pending_download_url))
            return
        self.on_manual_check_updates()

    def on_manual_check_updates(self):
        self._update_is_download_ready = False
        self._apply_check_btn_style(is_download_mode=False)
        self.btn_check_now.setEnabled(False)
        self.lbl_update_status.setText(t("update_status_checking"))
        self.lbl_update_status.setStyleSheet(f"color: {Theme.get_token('TEXT_MUTED')}; font-size: 11px;")

        self.update_thread = GitHubUpdateChecker(config=self.config, force=True, parent=None)
        self.update_thread.sig_update_available.connect(self.on_update_available_detected)
        self.update_thread.sig_check_finished.connect(self.on_manual_check_finished)
        self.update_thread.start()

    def on_update_available_detected(self, version: str, notes, html_url: str, download_url: str):
        self._pending_download_url = download_url or html_url

    def on_manual_check_finished(self, success: bool, status_code: str, message: str):
        self.btn_check_now.setEnabled(True)
        if success:
            if status_code == "update_available":
                self._update_is_download_ready = True
                self._apply_check_btn_style(is_download_mode=True)
                self.lbl_update_status.setText(t("update_status_available", version=message))
                self.lbl_update_status.setStyleSheet(f"color: {Theme.get_token('ACCENT_EMERALD')}; font-size: 11px; font-weight: 700;")
            else:
                self._update_is_download_ready = False
                self._apply_check_btn_style(is_download_mode=False)
                self.lbl_update_status.setText(t("update_status_latest", version=message))
                self.lbl_update_status.setStyleSheet(f"color: {Theme.get_token('TEXT_MUTED')}; font-size: 11px;")
        else:
            self._update_is_download_ready = False
            self._apply_check_btn_style(is_download_mode=False)
            self.lbl_update_status.setText(t("update_status_error"))
            self.lbl_update_status.setStyleSheet(f"color: {Theme.get_token('ACCENT_RED')}; font-size: 11px;")

    def _cleanup_update_thread(self):
        if hasattr(self, 'update_thread') and self.update_thread:
            try:
                self.update_thread.sig_update_available.disconnect()
            except Exception:
                pass
            try:
                self.update_thread.sig_check_finished.disconnect()
            except Exception:
                pass
            if hasattr(self.update_thread, 'stop'):
                self.update_thread.stop()
            elif self.update_thread.isRunning():
                self.update_thread.terminate()
                self.update_thread.wait(100)

    def done(self, r):
        self._cleanup_update_thread()
        super().done(r)

    def closeEvent(self, event):
        self._cleanup_update_thread()
        super().closeEvent(event)

    def reject(self):
        self._cleanup_update_thread()
        super().reject()

    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, t("settings_browse_title"))
        if folder:
            self.inp_out.setText(folder)

    def save_and_get_config(self):
        self.config.set("kaggle_username", self.inp_user.text().strip())
        self.config.set("kaggle_api_key", self.inp_key.text().strip())
        self.config.set("output_folder", self.inp_out.text().strip())
        self.config.set("local_model", self.cmb_model.currentText())
        self.config.set("enable_logging", self.switch_logging.isChecked())
        self.config.set("check_updates", self.switch_check_updates.isChecked())
        self.config.set("language", self.cmb_lang.currentData())
        return True


# ─── Delete Confirmation Dialog (Fixed Checkbox + Vector Badge) ───────────────

class DeleteConfirmDialog(QDialog):
    def __init__(self, count: int, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle(t("delete_dialog_title"))
        self.setMinimumWidth(410)
        self._theme_mode = Theme.get_mode()

        mode = self._theme_mode
        card_bg = Theme.get_token("CARD_BG", mode)
        text_head = Theme.get_token("TEXT_HEAD", mode)
        text_muted = Theme.get_token("TEXT_MUTED", mode)
        meta_bg = Theme.get_token("META_BG", mode)
        card_border = Theme.get_token("CARD_BORDER", mode)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {card_bg};
                border-radius: 12px;
            }}
            QLabel {{
                color: {text_head};
                background: transparent;
            }}
            {get_checkbox_qss(self._theme_mode, accent_color='#ef4444')}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 18, 20, 18)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        badge = VectorAlertBadge()
        top_row.addWidget(badge)

        msg_box = QVBoxLayout()
        msg_box.setSpacing(2)
        msg = format_delete_confirm_msg(count)
        lbl_msg = QLabel(msg)
        lbl_msg.setStyleSheet(f"font-size: 14.5px; font-weight: 800; color: {text_head}; background: transparent;")
        msg_box.addWidget(lbl_msg)

        lbl_desc = QLabel(t("delete_confirm_desc"))
        lbl_desc.setStyleSheet(f"color: {text_muted}; font-size: 11.5px; background: transparent;")
        msg_box.addWidget(lbl_desc)
        top_row.addLayout(msg_box, 1)
        layout.addLayout(top_row)

        # Checkbox with crisp white SVG checkmark & 1.5px border
        chk_box = QFrame()
        chk_box.setObjectName("chkCardFrame")
        chk_box.setStyleSheet(f"""
            QFrame#chkCardFrame {{
                background-color: {meta_bg};
                border: 1px solid {card_border};
                border-radius: 8px;
            }}
        """)
        cb_layout = QVBoxLayout(chk_box)
        cb_layout.setContentsMargins(10, 8, 10, 8)
        cb_layout.setSpacing(4)

        self.chk_delete_files = QCheckBox(t("delete_output_files_chk"))
        self.chk_delete_files.setToolTip(t("delete_output_files_tip"))
        self.chk_delete_files.setChecked(self.config.get("delete_output_files", False))
        cb_layout.addWidget(self.chk_delete_files)

        lbl_note = QLabel(t("delete_output_files_note"))
        lbl_note.setStyleSheet(f"color: {text_muted}; font-size: 10.5px; background: transparent;")
        cb_layout.addWidget(lbl_note)
        layout.addWidget(chk_box)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_cancel = QPushButton(t("btn_cancel"))
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: {meta_bg};
                color: {Theme.get_token('TEXT_BODY')};
                border: 1px solid {card_border};
                padding: 7px 16px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 12px;
            }}
            QPushButton:hover {{
                border-color: {Theme.get_token('CARD_BORDER_HOVER')};
            }}
        """)
        btn_cancel.clicked.connect(self.reject)

        btn_delete = QPushButton(t("btn_remove"))
        btn_delete.setCursor(Qt.PointingHandCursor)
        btn_delete.setStyleSheet("""
            QPushButton {{
                background-color: #ef4444;
                color: #ffffff;
                font-weight: 700;
                padding: 7px 18px;
                border-radius: 6px;
                border: none;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: #dc2626;
            }}
        """)
        btn_delete.clicked.connect(self.on_confirm)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_delete)
        layout.addLayout(btn_layout)

    def on_confirm(self):
        self.config.set("delete_output_files", self.chk_delete_files.isChecked())
        self.accept()

    def should_delete_files(self) -> bool:
        return self.chk_delete_files.isChecked()


# ─── Audio Track Selection Dialog (Channel-Strip Cards) ────────────────────────

class AudioTrackSelectDialog(QDialog):
    """Modern channel-strip card selector for multi-audio containers."""
    def __init__(self, audio_streams: list, file_name: str, parent=None):
        super().__init__(parent)
        self.audio_streams = audio_streams
        self.chosen_index = 0
        self.setWindowTitle(t("track_dialog_title"))
        self.setMinimumWidth(480)
        self._theme_mode = Theme.get_mode()

        mode = self._theme_mode
        card_bg = Theme.get_token("CARD_BG", mode)
        card_border = Theme.get_token("CARD_BORDER", mode)
        meta_bg = Theme.get_token("META_BG", mode)
        text_head = Theme.get_token("TEXT_HEAD", mode)
        text_muted = Theme.get_token("TEXT_MUTED", mode)
        accent = Theme.get_token("ACCENT_EMERALD", mode)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {card_bg};
                border-radius: 12px;
            }}
            QLabel {{
                color: {text_head};
                background: transparent;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 18, 20, 18)

        lbl_title = QLabel(t("track_dialog_header"))
        lbl_title.setStyleSheet(f"font-size: 15px; font-weight: 800; color: {text_head};")
        layout.addWidget(lbl_title)

        lbl_file = QLabel(t("track_dialog_file", file_name=file_name))
        lbl_file.setStyleSheet(f"font-size: 11.5px; color: {text_muted};")
        lbl_file.setWordWrap(True)
        layout.addWidget(lbl_file)

        lbl_desc = QLabel(t("track_dialog_desc"))
        lbl_desc.setStyleSheet(f"font-size: 12px; color: {text_head}; font-weight: 600;")
        layout.addWidget(lbl_desc)

        # Track list widget styled as channel strips
        self.track_list = QListWidget()
        self.track_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {meta_bg};
                border: 1px solid {card_border};
                border-radius: 8px;
                outline: 0px;
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 8px 10px;
                border-radius: 6px;
                font-size: 12px;
                color: {text_head};
                margin-bottom: 2px;
            }}
            QListWidget::item:selected {{
                background-color: rgba(16, 185, 129, 0.16);
                border: 1.5px solid {accent};
                font-weight: 700;
            }}
            QListWidget::item:hover {{
                background-color: rgba(16, 185, 129, 0.08);
            }}
        """)
        self.track_list.setSelectionMode(QListWidget.SingleSelection)

        for i, stream in enumerate(audio_streams):
            lang = stream.get("tags", {}).get("language", "") or "und"
            title = stream.get("tags", {}).get("title", "") or ""
            codec = stream.get("codec_name", "unknown").upper()
            channels = stream.get("channels", 2)
            ch_str = "Stereo" if channels == 2 else ("5.1 Surround" if channels == 6 else f"{channels} Ch")

            title_part = f" · {title}" if title else ""
            item_text = f"#{i + 1}  [{lang.upper()}]  {codec}  ·  {ch_str}{title_part}"
            item = QListWidgetItem(item_text)
            self.track_list.addItem(item)

        self.track_list.setCurrentRow(0)
        layout.addWidget(self.track_list)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_cancel = QPushButton(t("btn_cancel"))
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: {meta_bg};
                color: {Theme.get_token('TEXT_BODY')};
                border: 1px solid {card_border};
                padding: 7px 16px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 12px;
            }}
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_select = QPushButton(t("btn_select_track"))
        btn_select.setCursor(Qt.PointingHandCursor)
        btn_select.setStyleSheet(get_primary_button_qss(self._theme_mode))
        btn_select.clicked.connect(self._on_select)
        btn_layout.addWidget(btn_select)

        layout.addLayout(btn_layout)

    def _on_select(self):
        row = self.track_list.currentRow()
        self.chosen_index = row if row >= 0 else 0
        self.accept()

    def get_chosen_index(self) -> int:
        return self.chosen_index
