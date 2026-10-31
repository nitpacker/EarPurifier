import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QGroupBox, QFormLayout,
    QFileDialog, QListWidget, QListWidgetItem, QApplication
)
from PySide6.QtCore import Qt

from .theme import (
    TEXT_HEAD, TEXT_BODY, TEXT_MUTED, TEXT_FAINT,
    CARD_BORDER, CARD_BORDER_HOVER,
    ACCENT_EMERALD, ACCENT_MINT, ACCENT_TEAL, ACCENT_RED,
    get_combobox_qss, get_groupbox_qss
)
from .components import VectorAlertBadge

try:
    from config_manager import ConfigManager
except ImportError:
    from src.config_manager import ConfigManager

try:
    from i18n import t, is_rtl, format_delete_confirm_msg
except ImportError:
    from src.i18n import t, is_rtl, format_delete_confirm_msg


# ─── Settings Dialog ─────────────────────────────────────────────────────────

class SettingsDialog(QDialog):
    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle(t("settings_window_title"))
        self.setMinimumWidth(520)

        current_lang = self.config.get("language", "ar")
        rtl_mode = is_rtl(current_lang)

        # Set direction of the dialog explicitly
        self.setLayoutDirection(Qt.RightToLeft if rtl_mode else Qt.LeftToRight)
        self.apply_dialog_style(rtl_mode)
        self.init_ui(current_lang)

    def apply_dialog_style(self, rtl_mode: bool):
        self.setStyleSheet(f"""
            QDialog {{
                background-color: #ffffff;
            }}
            {get_groupbox_qss(rtl_mode)}
            QLabel {{
                color: {TEXT_BODY};
                font-size: 12px;
                font-weight: 600;
                background: transparent;
            }}
            QLineEdit {{
                background-color: #f7faf8;
                border: 1px solid {CARD_BORDER};
                border-radius: 6px;
                padding: 8px 12px;
                color: {TEXT_HEAD};
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {ACCENT_EMERALD};
                background-color: #ffffff;
            }}
            QCheckBox {{
                color: {TEXT_HEAD};
                font-size: 12px;
                font-weight: 600;
                spacing: 8px;
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 1px solid {CARD_BORDER};
                border-radius: 4px;
                background: #f7faf8;
            }}
            QCheckBox::indicator:checked {{
                background: {ACCENT_EMERALD};
                border-color: {ACCENT_EMERALD};
            }}
        """)

    def init_ui(self, current_lang: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 22, 24, 22)

        title_box = QHBoxLayout()
        self.lbl_title = QLabel(t("settings_header"))
        self.lbl_title.setStyleSheet(f"font-size: 18px; font-weight: 800; color: {TEXT_HEAD}; background: transparent;")
        title_box.addWidget(self.lbl_title)
        layout.addLayout(title_box)

        # ── Kaggle Credentials Group ──
        self.grp_kaggle = QGroupBox(t("settings_grp_kaggle"))
        self.form_kaggle = QFormLayout()
        self.form_kaggle.setSpacing(10)
        self.form_kaggle.setContentsMargins(14, 16, 14, 14)

        self.inp_user = QLineEdit(self.config.get("kaggle_username"))
        self.inp_user.setPlaceholderText(t("settings_kaggle_user_ph"))
        self.inp_key = QLineEdit(self.config.get("kaggle_api_key"))
        self.inp_key.setEchoMode(QLineEdit.Password)
        self.inp_key.setPlaceholderText("••••••••••••••••")

        self.lbl_user = QLabel(t("settings_kaggle_user"))
        self.lbl_key = QLabel(t("settings_kaggle_key"))
        self.form_kaggle.addRow(self.lbl_user, self.inp_user)
        self.form_kaggle.addRow(self.lbl_key, self.inp_key)
        self.grp_kaggle.setLayout(self.form_kaggle)

        # ── General & Engine Group ──
        self.grp_general = QGroupBox(t("settings_grp_general"))
        self.form_general = QFormLayout()
        self.form_general.setSpacing(10)
        self.form_general.setContentsMargins(14, 16, 14, 14)

        # Language Selector
        self.cmb_lang = QComboBox()
        self.cmb_lang.addItem("العربية", "ar")
        self.cmb_lang.addItem("English", "en")
        idx = 0 if current_lang == "ar" else 1
        self.cmb_lang.setCurrentIndex(idx)
        self.cmb_lang.setStyleSheet(get_combobox_qss(is_rtl(current_lang)))

        self.lbl_lang = QLabel(t("settings_language"))
        self.form_general.addRow(self.lbl_lang, self.cmb_lang)

        # Output Folder
        out_layout = QHBoxLayout()
        out_layout.setSpacing(8)
        self.inp_out = QLineEdit(self.config.get("output_folder"))
        self.inp_out.setPlaceholderText(t("settings_out_folder_ph"))
        self.btn_browse = QPushButton(t("settings_btn_browse"))
        self.btn_browse.setCursor(Qt.PointingHandCursor)
        self.btn_browse.setStyleSheet(f"""
            QPushButton {{
                background-color: #edf5f0;
                color: {TEXT_BODY};
                border: 1px solid {CARD_BORDER};
                padding: 7px 14px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 12px;
            }}
            QPushButton:hover {{
                border-color: {ACCENT_EMERALD};
                color: {ACCENT_EMERALD};
            }}
        """)
        self.btn_browse.clicked.connect(self.browse_output)
        out_layout.addWidget(self.inp_out)
        out_layout.addWidget(self.btn_browse)
        self.lbl_out = QLabel(t("settings_out_folder"))
        self.form_general.addRow(self.lbl_out, out_layout)

        # Local AI Model (Model names strictly preserved in English)
        self.cmb_model = QComboBox()
        self.cmb_model.addItems([
            "SOTA (RoFormer) - Requires High-End GPU",
            "Mid (MDX23C) - Balanced Quality & Speed",
            "Low (MDXNET) - Fast & Low VRAM"
        ])
        self.cmb_model.setCurrentText(self.config.get("local_model"))
        self.cmb_model.setStyleSheet(get_combobox_qss(is_rtl(current_lang)))
        self.lbl_model = QLabel(t("settings_local_model"))
        self.form_general.addRow(self.lbl_model, self.cmb_model)

        self.chk_logging = QCheckBox(t("settings_enable_logging"))
        self.chk_logging.setChecked(self.config.get("enable_logging", True))
        self.form_general.addRow("", self.chk_logging)
        self.grp_general.setLayout(self.form_general)

        # Save Button
        self.btn_save = QPushButton(t("settings_btn_save"))
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {ACCENT_EMERALD}, stop:1 {ACCENT_TEAL});
                color: #ffffff;
                font-size: 13px;
                font-weight: 700;
                padding: 10px 0px;
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {ACCENT_MINT}, stop:1 #0f766e);
            }}
        """)
        self.btn_save.clicked.connect(self.accept)

        layout.addWidget(self.grp_kaggle)
        layout.addWidget(self.grp_general)
        layout.addSpacing(6)
        layout.addWidget(self.btn_save)

    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, t("settings_browse_title"))
        if folder:
            self.inp_out.setText(folder)

    def save_and_get_config(self):
        self.config.set("kaggle_username", self.inp_user.text().strip())
        self.config.set("kaggle_api_key", self.inp_key.text().strip())
        self.config.set("output_folder", self.inp_out.text().strip())
        self.config.set("local_model", self.cmb_model.currentText())
        self.config.set("enable_logging", self.chk_logging.isChecked())
        self.config.set("language", self.cmb_lang.currentData())
        return True


# ─── Delete Confirmation Dialog (CLEAN, NO HIGHLIGHT, NO TRASH CONCEPT) ──────

class DeleteConfirmDialog(QDialog):
    def __init__(self, count: int, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle(t("delete_dialog_title"))
        self.setMinimumWidth(430)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: #ffffff;
                border-radius: 12px;
            }}
            QLabel {{
                color: {TEXT_HEAD};
                background: transparent;
                border: none;
            }}
            QCheckBox {{
                color: {TEXT_HEAD};
                font-size: 13px;
                font-weight: 600;
                spacing: 8px;
                background: transparent;
                border: none;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 1px solid {CARD_BORDER};
                border-radius: 4px;
                background: #f7faf8;
            }}
            QCheckBox::indicator:checked {{
                background: {ACCENT_RED};
                border-color: {ACCENT_RED};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 22, 24, 20)

        top_row = QHBoxLayout()
        top_row.setSpacing(14)
        badge = VectorAlertBadge()
        top_row.addWidget(badge)

        msg_box = QVBoxLayout()
        msg_box.setSpacing(3)
        msg = format_delete_confirm_msg(count)
        lbl_msg = QLabel(msg)
        lbl_msg.setStyleSheet(f"font-size: 15px; font-weight: 800; color: {TEXT_HEAD}; background: transparent; border: none;")
        msg_box.addWidget(lbl_msg)

        lbl_desc = QLabel(t("delete_confirm_desc"))
        lbl_desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent; border: none;")
        msg_box.addWidget(lbl_desc)
        top_row.addLayout(msg_box)
        top_row.addStretch()
        layout.addLayout(top_row)

        layout.addSpacing(4)

        self.chk_delete_files = QCheckBox(t("delete_output_files_chk"))
        self.chk_delete_files.setToolTip(t("delete_output_files_tip"))
        self.chk_delete_files.setChecked(self.config.get("delete_output_files", False))
        layout.addWidget(self.chk_delete_files)

        lbl_note = QLabel(t("delete_output_files_note"))
        lbl_note.setStyleSheet(f"color: {TEXT_FAINT}; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(lbl_note)

        layout.addSpacing(6)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_cancel = QPushButton(t("btn_cancel"))
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: #edf5f0;
                color: {TEXT_BODY};
                border: 1px solid {CARD_BORDER};
                padding: 8px 18px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 13px;
            }}
            QPushButton:hover {{
                border-color: {CARD_BORDER_HOVER};
                color: {TEXT_HEAD};
            }}
        """)
        btn_cancel.clicked.connect(self.reject)

        btn_delete = QPushButton(t("btn_remove"))
        btn_delete.setCursor(Qt.PointingHandCursor)
        btn_delete.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT_RED};
                color: #ffffff;
                font-weight: 700;
                padding: 8px 22px;
                border-radius: 6px;
                border: none;
                font-size: 13px;
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


# ─── Audio Track Selection Dialog ─────────────────────────────────────────────

class AudioTrackSelectDialog(QDialog):
    """
    Clean, styled PySide6 dialog for selecting an audio track from a multi-audio container.
    """
    def __init__(self, audio_streams: list, file_name: str, parent=None):
        super().__init__(parent)
        self.audio_streams = audio_streams
        self.chosen_index = 0
        self.setWindowTitle(t("track_dialog_title"))
        self.setMinimumWidth(500)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: #ffffff;
                border-radius: 12px;
            }}
            QLabel {{
                color: {TEXT_HEAD};
                background: transparent;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 22, 24, 20)

        # Header Title
        lbl_title = QLabel(t("track_dialog_header"))
        lbl_title.setStyleSheet(f"font-size: 16px; font-weight: 800; color: {TEXT_HEAD};")
        layout.addWidget(lbl_title)

        lbl_file = QLabel(t("track_dialog_file", file_name=file_name))
        lbl_file.setStyleSheet(f"font-size: 12px; color: {TEXT_MUTED}; font-weight: 500;")
        lbl_file.setWordWrap(True)
        layout.addWidget(lbl_file)

        lbl_desc = QLabel(t("track_dialog_desc"))
        lbl_desc.setStyleSheet(f"font-size: 13px; color: {TEXT_BODY}; font-weight: 600;")
        layout.addWidget(lbl_desc)

        # Track list widget
        self.track_list = QListWidget()
        self.track_list.setStyleSheet(f"""
            QListWidget {{
                background-color: #f7faf8;
                border: 1px solid {CARD_BORDER};
                border-radius: 8px;
                outline: 0px;
                padding: 6px;
            }}
            QListWidget::item {{
                padding: 10px 12px;
                border-radius: 6px;
                font-size: 12.5px;
                color: {TEXT_HEAD};
            }}
            QListWidget::item:selected {{
                background-color: rgba(16, 185, 129, 0.16);
                color: {TEXT_HEAD};
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
            codec = stream.get("codec_name", "unknown")
            channels = stream.get("channels", 0)

            title_part = f" ({title})" if title else ""
            item_text = t(
                "track_item_format",
                num=i + 1,
                lang=lang.upper(),
                title=title_part,
                codec=codec,
                channels=channels
            )
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
                background-color: #edf5f0;
                color: {TEXT_BODY};
                border: 1px solid {CARD_BORDER};
                padding: 8px 18px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 13px;
            }}
            QPushButton:hover {{
                border-color: {CARD_BORDER_HOVER};
                color: {TEXT_HEAD};
            }}
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_select = QPushButton(t("btn_select_track"))
        btn_select.setCursor(Qt.PointingHandCursor)
        btn_select.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {ACCENT_EMERALD}, stop:1 {ACCENT_TEAL});
                color: #ffffff;
                font-size: 13px;
                font-weight: 700;
                padding: 8px 22px;
                border: none;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {ACCENT_MINT}, stop:1 #0f766e);
            }}
        """)
        btn_select.clicked.connect(self._on_select)
        btn_layout.addWidget(btn_select)

        layout.addLayout(btn_layout)

    def _on_select(self):
        row = self.track_list.currentRow()
        self.chosen_index = row if row >= 0 else 0
        self.accept()

    def get_chosen_index(self) -> int:
        return self.chosen_index
