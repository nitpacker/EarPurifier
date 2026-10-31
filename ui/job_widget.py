import os
from datetime import datetime, timezone
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QProgressBar, QFrame
)
from PySide6.QtCore import Qt, QTimer, Signal, QSize

from .theme import (
    Theme, ThemeMode, FONT_FAMILY, FONT_MONO,
    get_checkbox_qss, get_yellow_folder_icon
)
from .components import CleanCloseButton, RotatingSpinner

try:
    from i18n import t, is_rtl, translate_worker_message
except ImportError:
    from src.i18n import t, is_rtl, translate_worker_message


# ─── 3-Zone Compact Audio Track Card Presentation View ────────────────────────

class JobWidget(QWidget):
    """
    Presentation view for an individual audio purification job card.
    Structured into a 3-zone compact layout (~88px height):
      - Zone 1: Header (Checkbox, Format, File Title, Status Badge, Micro-actions)
      - Zone 2: Monospaced Audio Metadata Row (Duration, Model, Channels, ETA)
      - Zone 3: Progress & Action Footer (6px Gradient Bar, Worker Message, 'Show in Folder')
    """
    sig_abort_clicked = Signal(str)
    sig_delete_clicked = Signal(str)
    sig_open_folder_clicked = Signal(str)
    sig_selection_toggled = Signal(str, bool)

    # Aliases for backward compatibility
    abort_requested = sig_abort_clicked
    delete_requested = sig_delete_clicked
    selection_changed = sig_selection_toggled

    def __init__(self, job_id: str, job_dict: dict, mode: str = "Cloud (Kaggle)", parent=None):
        super().__init__(parent)
        self.job_id = job_id
        self.job_dict = job_dict
        self.video_path = job_dict.get("original_media") or job_dict.get("original_video", "")
        self.duration = job_dict.get("duration", 0.0)
        self.mode = mode
        self.current_status = "PENDING"
        self.current_badge_state = "queued"
        self.remaining_seconds = 0
        self._raw_message = ""
        self._theme_mode = Theme.get_mode()

        # Elapsed seconds calculation
        try:
            if "final_elapsed_seconds" in job_dict:
                self.elapsed_seconds = job_dict["final_elapsed_seconds"]
            elif job_dict.get("status", "PENDING") == "PENDING":
                self.elapsed_seconds = 0
            else:
                start_time_str = job_dict.get("started_at", job_dict.get("added_at", datetime.now(timezone.utc).isoformat()))
                start_time = datetime.fromisoformat(start_time_str)
                status = job_dict.get("status", "PENDING")
                if status in ["COMPLETED", "ERROR", "ABORTED"]:
                    updated_at = datetime.fromisoformat(job_dict.get("updated_at", datetime.now(timezone.utc).isoformat()))
                    self.elapsed_seconds = max(0, int((updated_at - start_time).total_seconds()))
                else:
                    self.elapsed_seconds = max(0, int((datetime.now(timezone.utc) - start_time).total_seconds()))
        except Exception:
            self.elapsed_seconds = 0

        self.init_ui()
        if "status" in job_dict:
            self.update_status(job_dict["status"])
        if "message" in job_dict:
            self.update_message(job_dict["message"])

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(self.width() if self.width() > 0 else 600, 118)

    def init_ui(self):
        card_layout = QVBoxLayout(self)
        card_layout.setContentsMargins(4, 2, 4, 2)
        card_layout.setSpacing(0)

        # Elevated Frame Card (Target Height: ~96-102px Compact Studio Card)
        self.frame = QFrame()
        self.frame.setObjectName("jobRow")
        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(14, 9, 14, 9)
        frame_layout.setSpacing(6)

        # ── Zone 1: Header Row (~22px) ──
        zone1_layout = QHBoxLayout()
        zone1_layout.setContentsMargins(0, 0, 0, 0)
        zone1_layout.setSpacing(8)

        # Checkbox with crisp SVG checkmark
        self.chk_select = QCheckBox()
        self.chk_select.setVisible(False)
        self.chk_select.setStyleSheet(get_checkbox_qss(self._theme_mode))
        self.chk_select.stateChanged.connect(lambda state: self.sig_selection_toggled.emit(self.job_id, state == Qt.Checked.value))
        zone1_layout.addWidget(self.chk_select)

        # Audio/Video Format Pill
        ext = os.path.splitext(self.video_path)[1].replace(".", "").upper() or "AUD"
        self.lbl_format = QLabel(ext[:4])
        self.lbl_format.setStyleSheet(f"""
            font-family: {FONT_MONO};
            font-size: 9.5px;
            font-weight: 800;
            padding: 1px 5px;
            border-radius: 4px;
        """)
        zone1_layout.addWidget(self.lbl_format)

        # File Name (clean, readable text without obstructive long-path tooltips)
        self.lbl_name = QLabel(os.path.basename(self.video_path))
        self.lbl_name.setStyleSheet("font-weight: 700; font-size: 12.5px; background: transparent;")
        align = (Qt.AlignRight | Qt.AlignAbsolute | Qt.AlignVCenter) if is_rtl() else (Qt.AlignLeft | Qt.AlignAbsolute | Qt.AlignVCenter)
        self.lbl_name.setAlignment(align)
        zone1_layout.addWidget(self.lbl_name, 1)

        # Status Badge Pill
        self.lbl_badge = QLabel(t("badge_queued"))
        zone1_layout.addWidget(self.lbl_badge)

        # Abort Button (active states)
        self.btn_abort = QPushButton(t("btn_abort"))
        self.btn_abort.setCursor(Qt.PointingHandCursor)
        self.btn_abort.setStyleSheet("""
            QPushButton {
                background-color: rgba(245, 158, 11, 0.14);
                color: #b45309;
                font-size: 10.5px;
                font-weight: 700;
                padding: 2px 7px;
                border-radius: 4px;
                border: 1px solid rgba(245, 158, 11, 0.3);
            }
            QPushButton:hover {
                background-color: rgba(245, 158, 11, 0.24);
            }
        """)
        self.btn_abort.clicked.connect(lambda: self.sig_abort_clicked.emit(self.job_id))
        zone1_layout.addWidget(self.btn_abort)

        # Clean '✕' Close Button
        self.btn_delete = CleanCloseButton()
        self.btn_delete.clicked.connect(lambda: self.sig_delete_clicked.emit(self.job_id))
        zone1_layout.addWidget(self.btn_delete)

        frame_layout.addLayout(zone1_layout)

        # ── Zone 2: Monospaced Metadata Row (~20px) ──
        self.meta_container = QFrame()
        self.meta_container.setObjectName("metaRow")
        meta_layout = QHBoxLayout(self.meta_container)
        meta_layout.setContentsMargins(6, 2, 6, 2)
        meta_layout.setSpacing(8)

        # Duration Tag
        emins, esecs = divmod(int(self.duration), 60)
        dur_txt = f"{emins:02d}:{esecs:02d}" if self.duration > 0 else "--:--"
        self.lbl_meta_dur = QLabel(dur_txt)
        meta_layout.addWidget(self.lbl_meta_dur)

        self.sep1 = QLabel("·")
        meta_layout.addWidget(self.sep1)

        # Model Tag (rich text with bold model name)
        self.lbl_meta_model = QLabel()
        meta_layout.addWidget(self.lbl_meta_model)

        self.sep2 = QLabel("·")
        meta_layout.addWidget(self.sep2)

        # Channels / Stream Spec
        probe = self.job_dict.get("probe_result") or {}
        streams = probe.get("audio_streams", [])
        sel_idx = self.job_dict.get("selected_audio_stream", 0)
        if streams and sel_idx < len(streams):
            st = streams[sel_idx]
            ch = st.get("channels", 2)
            ch_txt = "Stereo 2.0 (48kHz)" if ch == 2 else ("5.1 Surround" if ch == 6 else f"{ch} Channels")
        else:
            ch_txt = "Stereo 2.0 (48kHz)"
        self.lbl_meta_channels = QLabel(ch_txt)
        meta_layout.addWidget(self.lbl_meta_channels)

        # ETA Tag / Status Suffix (only shown when relevant!)
        self.sep3 = QLabel("·")
        self.lbl_eta = QLabel("")
        meta_layout.addWidget(self.sep3)
        meta_layout.addWidget(self.lbl_eta)
        self.sep3.setVisible(False)
        self.lbl_eta.setVisible(False)

        meta_layout.addStretch()
        frame_layout.addWidget(self.meta_container)

        # ── Zone 3: Progress & Action Footer (Comfortable Breathing Room) ──
        self.footer_container = QWidget()
        self.footer_container.setStyleSheet("background: transparent;")
        footer_layout = QVBoxLayout(self.footer_container)
        footer_layout.setContentsMargins(0, 2, 0, 0)
        footer_layout.setSpacing(5)

        # 6px Gradient Progress Bar
        self.progress = QProgressBar()
        self.progress.setFixedHeight(5)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        footer_layout.addWidget(self.progress)

        # Status text row
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(6)

        # Smooth Rotating Arrows Spinner (starts when running)
        self.spinner = RotatingSpinner(14)
        status_row.addWidget(self.spinner)

        self.lbl_message = QLabel("")
        self.lbl_message.setMinimumHeight(18)
        self.lbl_message.setStyleSheet("font-size: 11px; font-weight: 500; background: transparent;")
        status_row.addWidget(self.lbl_message, 1)

        self.lbl_elapsed = QLabel("")
        self.lbl_elapsed.setStyleSheet(f"font-family: {FONT_MONO}; font-size: 10.5px; background: transparent;")
        status_row.addWidget(self.lbl_elapsed)

        # 'Show in Folder' Button (appears on COMPLETED)
        self.btn_show_folder = QPushButton(t("btn_show_in_folder"))
        folder_icon = get_yellow_folder_icon()
        if folder_icon:
            self.btn_show_folder.setIcon(folder_icon)
            self.btn_show_folder.setIconSize(QSize(14, 14))
        self.btn_show_folder.setCursor(Qt.PointingHandCursor)
        self.btn_show_folder.setVisible(False)
        self.btn_show_folder.clicked.connect(lambda: self.sig_open_folder_clicked.emit(self.job_id))
        status_row.addWidget(self.btn_show_folder)

        footer_layout.addLayout(status_row)
        frame_layout.addWidget(self.footer_container)

        card_layout.addWidget(self.frame)

        self.apply_theme(self._theme_mode)
        self._set_badge_style("queued")

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._on_timer_tick)

    def _update_model_label(self):
        mode = self._theme_mode
        text_head = Theme.get_token("TEXT_HEAD", mode)
        text_muted = Theme.get_token("TEXT_MUTED", mode)
        model_name = self.job_dict.get("model") or ("Kaggle T4" if "Cloud" in self.mode else "RoFormer")
        mode_prefix = t("tag_mode_cloud") if "Cloud" in self.mode else t("tag_mode_local")
        mono_font = Theme.resolve_mono_font()
        self.lbl_meta_model.setText(
            f"<span style='color: {text_muted}; font-family: {mono_font}; font-size: 11px;'>{mode_prefix}: "
            f"<b style='color: {text_head};'>{model_name}</b></span>"
        )

    def apply_theme(self, theme_mode: str):
        self._theme_mode = theme_mode
        card_bg = Theme.get_token("CARD_BG", theme_mode)
        card_border = Theme.get_token("CARD_BORDER", theme_mode)
        card_border_hover = Theme.get_token("CARD_BORDER_HOVER", theme_mode)
        meta_bg = Theme.get_token("META_BG", theme_mode)
        text_head = Theme.get_token("TEXT_HEAD", theme_mode)
        text_muted = Theme.get_token("TEXT_MUTED", theme_mode)
        text_faint = Theme.get_token("TEXT_FAINT", theme_mode)
        accent_emerald = Theme.get_token("ACCENT_EMERALD", theme_mode)
        accent_teal = Theme.get_token("ACCENT_TEAL", theme_mode)
        mono_font = Theme.resolve_mono_font()

        self.frame.setStyleSheet(f"""
            QFrame#jobRow {{
                background-color: {card_bg};
                border: 1px solid {card_border};
                border-radius: 9px;
            }}
            QFrame#jobRow:hover {{
                border-color: {card_border_hover};
            }}
        """)
        self.frame.setMinimumHeight(108)

        self.meta_container.setStyleSheet(f"""
            QFrame#metaRow {{
                background-color: {meta_bg};
                border: 1px solid {card_border};
                border-radius: 6px;
            }}
            QLabel {{
                font-family: {mono_font};
                font-size: 11px;
                color: {text_muted};
                background: transparent;
            }}
        """)

        self.lbl_format.setStyleSheet(f"""
            font-family: {mono_font};
            font-size: 9.5px;
            font-weight: 800;
            color: {accent_emerald};
            background-color: {meta_bg};
            border: 1px solid {card_border};
            border-radius: 4px;
            padding: 1px 4px;
        """)

        self.lbl_meta_dur.setStyleSheet(f"""
            font-family: {mono_font};
            font-size: 11px;
            font-weight: 700;
            color: {accent_emerald};
            background: transparent;
        """)

        for s in [self.sep1, self.sep2, self.sep3]:
            s.setStyleSheet(f"color: {text_faint}; font-family: {mono_font}; font-size: 11px; background: transparent;")

        self._update_model_label()

        self.lbl_name.setStyleSheet(f"font-weight: 700; font-size: 12.5px; color: {text_head}; background: transparent;")
        self.lbl_elapsed.setStyleSheet(f"font-family: {mono_font}; font-size: 10.5px; color: {text_faint}; background: transparent;")
        self.chk_select.setStyleSheet(get_checkbox_qss(theme_mode))

        self.progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {card_border};
                border: none;
                border-radius: 2.5px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {accent_emerald}, stop:1 {accent_teal});
                border-radius: 2.5px;
            }}
        """)

        self.btn_show_folder.setStyleSheet(f"""
            QPushButton {{
                background-color: {meta_bg};
                color: {accent_emerald};
                border: 1px solid {card_border};
                border-radius: 6px;
                font-weight: 700;
                font-size: 11px;
                padding: 3px 10px;
            }}
            QPushButton:hover {{
                border-color: {accent_emerald};
                background-color: rgba(16, 185, 129, 0.12);
            }}
        """)

        self._set_badge_style(self.current_badge_state)

    def _set_badge_style(self, state: str):
        self.current_badge_state = state
        mode = self._theme_mode
        accent_blue = Theme.get_token("ACCENT_BLUE", mode)
        accent_emerald = Theme.get_token("ACCENT_EMERALD", mode)
        accent_amber = Theme.get_token("ACCENT_AMBER", mode)
        accent_red = Theme.get_token("ACCENT_RED", mode)
        text_faint = Theme.get_token("TEXT_FAINT", mode)

        if state == "running":
            self.lbl_badge.setText(t("badge_running"))
            self.lbl_badge.setStyleSheet(f"""
                background-color: rgba(2, 132, 199, 0.12);
                color: {accent_blue};
                border: 1px solid rgba(2, 132, 199, 0.3);
                font-size: 10px;
                font-weight: 800;
                padding: 1px 7px;
                border-radius: 10px;
            """)
        elif state == "completed":
            self.lbl_badge.setText(t("badge_completed"))
            self.lbl_badge.setStyleSheet(f"""
                background-color: rgba(16, 185, 129, 0.12);
                color: {accent_emerald};
                border: 1px solid rgba(16, 185, 129, 0.3);
                font-size: 10px;
                font-weight: 800;
                padding: 1px 7px;
                border-radius: 10px;
            """)
        elif state == "aborted":
            self.lbl_badge.setText(t("badge_aborted"))
            self.lbl_badge.setStyleSheet(f"""
                background-color: rgba(245, 158, 11, 0.12);
                color: {accent_amber};
                border: 1px solid rgba(245, 158, 11, 0.3);
                font-size: 10px;
                font-weight: 800;
                padding: 1px 7px;
                border-radius: 10px;
            """)
        elif state == "failed":
            self.lbl_badge.setText(t("badge_failed"))
            self.lbl_badge.setStyleSheet(f"""
                background-color: rgba(239, 68, 68, 0.12);
                color: {accent_red};
                border: 1px solid rgba(239, 68, 68, 0.3);
                font-size: 10px;
                font-weight: 800;
                padding: 1px 7px;
                border-radius: 10px;
            """)
        else:
            self.lbl_badge.setText(t("badge_queued"))
            self.lbl_badge.setStyleSheet(f"""
                background-color: rgba(134, 161, 147, 0.12);
                color: {text_faint};
                border: 1px solid rgba(134, 161, 147, 0.3);
                font-size: 10px;
                font-weight: 800;
                padding: 1px 7px;
                border-radius: 10px;
            """)

    def set_selection_mode(self, enabled: bool):
        self.chk_select.setVisible(enabled)
        if not enabled:
            self.chk_select.setChecked(False)

    def set_selected(self, checked: bool):
        self.chk_select.setChecked(checked)

    def is_selected(self) -> bool:
        return self.chk_select.isChecked()

    def _on_timer_tick(self):
        if self.current_status in ["COMPLETED", "ERROR", "ABORTED"]:
            self.timer.stop()
            return
        if self.current_status == "PENDING":
            return

        self.elapsed_seconds += 1
        emins, esecs = divmod(self.elapsed_seconds, 60)
        self.lbl_elapsed.setText(f"{t('label_elapsed')} {emins:02d}:{esecs:02d}")

        if self.mode == "Cloud (Kaggle)":
            if self.current_status in ["PENDING", "EXTRACTING", "UPLOADING"]:
                self.lbl_eta.setText(t("eta_calculating"))
            elif self.current_status in ["PROCESSING_CLOUD", "DOWNLOADING", "REMUXING"]:
                if not getattr(self, "eta_initialized", False):
                    self.remaining_seconds = max(60, int(150 + (self.duration * 1.5)))
                    self.eta_initialized = True
                self.remaining_seconds -= 1
                if self.remaining_seconds > 0:
                    mins, secs = divmod(self.remaining_seconds, 60)
                    self.lbl_eta.setText(t("eta_time_ms", mins=mins, secs=secs) if mins > 0 else t("eta_time_s", secs=secs))
                else:
                    self.lbl_eta.setText(t("eta_anytime"))

    def update_status(self, status: str):
        self.current_status = status
        mode = self._theme_mode
        accent_blue = Theme.get_token("ACCENT_BLUE", mode)
        accent_emerald = Theme.get_token("ACCENT_EMERALD", mode)
        accent_amber = Theme.get_token("ACCENT_AMBER", mode)
        accent_red = Theme.get_token("ACCENT_RED", mode)
        text_muted = Theme.get_token("TEXT_MUTED", mode)

        is_running = status in ["EXTRACTING", "UPLOADING", "PROCESSING_CLOUD", "PROCESSING_LOCAL", "DOWNLOADING", "REMUXING"]
        is_active = is_running or status == "PENDING"
        self.btn_abort.setVisible(is_active)

        if is_running:
            self.spinner.start()
            if not self.timer.isActive():
                self.timer.start()
        else:
            self.spinner.stop()

        mono_font = Theme.resolve_mono_font()

        if status == "COMPLETED":
            self.timer.stop()
            self._set_badge_style("completed")
            self.sep3.setVisible(True)
            self.lbl_eta.setVisible(True)
            self.lbl_eta.setStyleSheet(f"font-family: {mono_font}; font-size: 11px; font-weight: 700; color: {accent_emerald}; background: transparent;")
            self.lbl_eta.setText(t("meta_saved_to_output"))

            self._raw_message = "Purification complete · Audio isolated"
            self.lbl_message.setText(t("msg_purification_complete"))
            self.lbl_message.setStyleSheet(f"font-size: 11px; font-weight: 500; color: {text_muted}; background: transparent;")
            self.progress.setVisible(False)
            self.lbl_elapsed.setVisible(False)
            self.btn_show_folder.setVisible(True)

        elif status == "ABORTED":
            self.timer.stop()
            self._set_badge_style("aborted")
            self.sep3.setVisible(False)
            self.lbl_eta.setVisible(False)
            self._raw_message = "Job aborted"
            self.lbl_message.setText(t("msg_job_aborted"))
            self.lbl_message.setStyleSheet(f"font-size: 11px; font-weight: 500; color: {accent_amber}; background: transparent;")
            self.progress.setVisible(False)
            self.lbl_elapsed.setVisible(True)
            self.btn_show_folder.setVisible(False)

        elif status in ["ERROR", "FAILED"]:
            self.timer.stop()
            self._set_badge_style("failed")
            self.sep3.setVisible(False)
            self.lbl_eta.setVisible(False)
            self._raw_message = "Processing failed"
            self.lbl_message.setText(t("msg_processing_failed"))
            self.lbl_message.setStyleSheet(f"font-size: 11px; font-weight: 500; color: {accent_red}; background: transparent;")
            self.progress.setVisible(False)
            self.lbl_elapsed.setVisible(True)
            self.btn_show_folder.setVisible(False)

        elif status == "PENDING":
            self._set_badge_style("queued")
            self.sep3.setVisible(True)
            self.lbl_eta.setVisible(True)
            self.lbl_eta.setStyleSheet(f"font-family: {mono_font}; font-size: 11px; font-weight: 700; color: {accent_amber}; background: transparent;")
            self.lbl_eta.setText(t("eta_in_queue"))
            self._raw_message = "Waiting in queue..."
            self.lbl_message.setText(t("msg_waiting_queue"))
            self.lbl_message.setStyleSheet(f"font-size: 11px; font-weight: 500; color: {text_muted}; background: transparent;")
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
            self.lbl_elapsed.setVisible(False)
            self.btn_show_folder.setVisible(False)

        else: # is_running
            self._set_badge_style("running")
            self.sep3.setVisible(self.mode == "Cloud (Kaggle)")
            self.lbl_eta.setVisible(self.mode == "Cloud (Kaggle)")
            self.lbl_eta.setStyleSheet(f"font-family: {mono_font}; font-size: 11px; font-weight: 700; color: {accent_blue}; background: transparent;")
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
            self.lbl_elapsed.setVisible(True)
            self.btn_show_folder.setVisible(False)
            if not self._raw_message or self._raw_message == "Waiting in queue...":
                self._raw_message = "Isolating vocals with AI..."
                self.lbl_message.setText(t("msg_isolating_vocals"))
            self.lbl_message.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {accent_emerald}; background: transparent;")

    def update_message(self, message: str):
        self._raw_message = message
        self.lbl_message.setText(translate_worker_message(message))

    def update_state(self, job_data: dict):
        self.job_dict = job_data
        if "duration" in job_data:
            self.duration = job_data["duration"]
        if "status" in job_data and job_data["status"] != self.current_status:
            self.update_status(job_data["status"])
        if "message" in job_data and job_data["message"] != self._raw_message:
            self.update_message(job_data["message"])

    def retranslate_ui(self):
        self.btn_abort.setText(t("btn_abort"))
        self.btn_delete.retranslate_ui()
        self.btn_show_folder.setText(t("btn_show_in_folder"))
        folder_icon = get_yellow_folder_icon()
        if folder_icon:
            self.btn_show_folder.setIcon(folder_icon)
        align = (Qt.AlignRight | Qt.AlignAbsolute | Qt.AlignVCenter) if is_rtl() else (Qt.AlignLeft | Qt.AlignAbsolute | Qt.AlignVCenter)
        self.lbl_name.setAlignment(align)
        self._set_badge_style(self.current_badge_state)
        self._update_model_label()
        if self._raw_message:
            self.lbl_message.setText(translate_worker_message(self._raw_message))
        if self.elapsed_seconds > 0:
            emins, esecs = divmod(self.elapsed_seconds, 60)
            self.lbl_elapsed.setText(f"{t('label_elapsed')} {emins:02d}:{esecs:02d}")

