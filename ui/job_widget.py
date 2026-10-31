import os
from datetime import datetime, timezone
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QProgressBar, QFrame
)
from PySide6.QtCore import Qt, QTimer, Signal

from .theme import (
    CARD_BG, CARD_BORDER, CARD_BORDER_HOVER,
    TEXT_HEAD, TEXT_BODY, TEXT_MUTED, TEXT_FAINT,
    ACCENT_EMERALD, ACCENT_MINT, ACCENT_TEAL, ACCENT_CYAN,
    ACCENT_BLUE, ACCENT_AMBER, ACCENT_RED
)
from .components import CleanCloseButton

try:
    from i18n import t, translate_worker_message
except ImportError:
    from src.i18n import t, translate_worker_message


# ─── Job Card Presentation View ───────────────────────────────────────────────

class JobWidget(QWidget):
    """
    Presentation view for an individual audio purification job card.
    Emits Qt signals on user actions (abort, delete, select, open folder)
    without mutating background managers directly.
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
        
        # Calculate elapsed seconds ignoring the PENDING wait time
        try:
            if "final_elapsed_seconds" in job_dict:
                self.elapsed_seconds = job_dict["final_elapsed_seconds"]
            elif job_dict.get("status", "PENDING") == "PENDING":
                self.elapsed_seconds = 0
            else:
                # Job is active or finished without final_elapsed_seconds
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

        card_layout = QVBoxLayout(self)
        card_layout.setContentsMargins(6, 4, 6, 4)

        # Polished Card Row (10px radius, gentle border, peaceful botanical styling)
        self.frame = QFrame()
        self.frame.setObjectName("jobRow")
        self.frame.setStyleSheet(f"""
            QFrame#jobRow {{
                background-color: {CARD_BG};
                border: 1px solid {CARD_BORDER};
                border-radius: 10px;
            }}
            QFrame#jobRow:hover {{
                border-color: {CARD_BORDER_HOVER};
                background-color: #ffffff;
            }}
        """)
        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(16, 12, 16, 12)
        frame_layout.setSpacing(8)

        # Line 1: [Checkbox] [Status Icon] [File Name] [Tags...] [ETA/Badge] [Abort] [✕ Button]
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self.chk_select = QCheckBox()
        self.chk_select.setVisible(False)
        self.chk_select.setStyleSheet(f"""
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {CARD_BORDER};
                border-radius: 4px;
                background: #f7faf8;
            }}
            QCheckBox::indicator:checked {{
                background: {ACCENT_EMERALD};
                border-color: {ACCENT_EMERALD};
            }}
        """)
        self.chk_select.stateChanged.connect(lambda state: self.sig_selection_toggled.emit(self.job_id, state == Qt.Checked.value))
        top_row.addWidget(self.chk_select)

        # Status Circle Indicator
        self.lbl_status_icon = QLabel("●")
        self.lbl_status_icon.setStyleSheet(f"font-size: 14px; color: {TEXT_FAINT}; background: transparent;")
        top_row.addWidget(self.lbl_status_icon)

        # Video File Name
        self.lbl_name = QLabel(os.path.basename(self.video_path))
        self.lbl_name.setStyleSheet(f"font-weight: 700; font-size: 13.5px; color: {TEXT_HEAD}; background: transparent;")
        self.lbl_name.setToolTip(self.video_path)
        top_row.addWidget(self.lbl_name)

        # Engine Tag (Soft Mint Pill)
        model_name = job_dict.get("model")
        if not model_name:
            model_name = "Kaggle T4" if "Cloud" in mode else "RoFormer"
        
        mode_prefix = t("tag_mode_cloud") if "Cloud" in mode else t("tag_mode_local")
        self.tag_engine = QLabel(f"{mode_prefix} · {model_name}")
        self.tag_engine.setStyleSheet(f"""
            background-color: rgba(16, 185, 129, 0.1);
            color: #047857;
            font-size: 11px;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 4px;
        """)
        top_row.addWidget(self.tag_engine)

        # Elapsed Time Tag
        emins, esecs = divmod(self.elapsed_seconds, 60)
        initial_elapsed = t("time_ms_format", mins=emins, secs=esecs) if emins > 0 else t("time_s_format", secs=esecs)
        self.tag_elapsed = QLabel(initial_elapsed)
        self.tag_elapsed.setStyleSheet(f"""
            background-color: #edf5f0;
            color: {TEXT_MUTED};
            font-size: 11px;
            font-weight: 600;
            padding: 2px 7px;
            border-radius: 4px;
        """)
        top_row.addWidget(self.tag_elapsed)

        top_row.addStretch()

        # ETA Tag (Cloud Only)
        self.lbl_eta = QLabel("")
        self.lbl_eta.setStyleSheet(f"""
            color: {ACCENT_TEAL};
            background-color: #f0fdf4;
            font-size: 11px;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 4px;
            border: 1px solid #bbf7d0;
        """)
        if self.mode == "Cloud (Kaggle)":
            top_row.addWidget(self.lbl_eta)

        # Status Badge Pill
        self.lbl_badge = QLabel(t("badge_queued"))
        self._set_badge_style("queued")
        top_row.addWidget(self.lbl_badge)

        # Abort Button (when active)
        self.btn_abort = QPushButton(t("btn_abort"))
        self.btn_abort.setCursor(Qt.PointingHandCursor)
        self.btn_abort.setStyleSheet(f"""
            QPushButton {{
                background-color: #fef3c7;
                color: #b45309;
                font-size: 11px;
                font-weight: 700;
                padding: 4px 10px;
                border-radius: 4px;
                border: 1px solid #fde68a;
            }}
            QPushButton:hover {{
                background-color: #fde68a;
            }}
        """)
        self.btn_abort.clicked.connect(lambda: self.sig_abort_clicked.emit(self.job_id))
        top_row.addWidget(self.btn_abort)

        # Clean '✕' Button (NO TRASH ICON!)
        self.btn_delete = CleanCloseButton()
        self.btn_delete.clicked.connect(lambda: self.sig_delete_clicked.emit(self.job_id))
        top_row.addWidget(self.btn_delete)

        frame_layout.addLayout(top_row)

        # Line 2: Progress Indicator & Status Message
        self.bottom_container = QWidget()
        bottom_row = QHBoxLayout(self.bottom_container)
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(10)

        # Progress Bar (Slim 4px sprout-teal gradient)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: #e2ede7;
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {ACCENT_MINT}, stop:0.5 {ACCENT_EMERALD}, stop:1 {ACCENT_CYAN});
                border-radius: 2px;
            }}
        """)
        bottom_row.addWidget(self.progress, 1)

        self.lbl_message = QLabel("")
        self.lbl_message.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; font-weight: 500; background: transparent;")
        bottom_row.addWidget(self.lbl_message)

        frame_layout.addWidget(self.bottom_container)
        card_layout.addWidget(self.frame)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._on_timer_tick)

    def _set_badge_style(self, state: str):
        self.current_badge_state = state
        if state == "running":
            self.lbl_badge.setText(t("badge_running"))
            self.lbl_badge.setStyleSheet(f"""
                background-color: {ACCENT_BLUE};
                color: #ffffff;
                font-size: 10px;
                font-weight: 800;
                padding: 3px 10px;
                border-radius: 12px;
                letter-spacing: 0.5px;
            """)
            self.lbl_status_icon.setText("●")
            self.lbl_status_icon.setStyleSheet(f"font-size: 14px; color: {ACCENT_BLUE}; background: transparent;")
        elif state == "completed":
            self.lbl_badge.setText(t("badge_completed"))
            self.lbl_badge.setStyleSheet(f"""
                background-color: {ACCENT_EMERALD};
                color: #ffffff;
                font-size: 10px;
                font-weight: 800;
                padding: 3px 10px;
                border-radius: 12px;
                letter-spacing: 0.5px;
            """)
            self.lbl_status_icon.setText("✓")
            self.lbl_status_icon.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {ACCENT_EMERALD}; background: transparent;")
        elif state == "aborted":
            self.lbl_badge.setText(t("badge_aborted"))
            self.lbl_badge.setStyleSheet(f"""
                background-color: {ACCENT_AMBER};
                color: #ffffff;
                font-size: 10px;
                font-weight: 800;
                padding: 3px 10px;
                border-radius: 12px;
                letter-spacing: 0.5px;
            """)
            self.lbl_status_icon.setText("○")
            self.lbl_status_icon.setStyleSheet(f"font-size: 14px; color: {ACCENT_AMBER}; background: transparent;")
        elif state == "failed":
            self.lbl_badge.setText(t("badge_failed"))
            self.lbl_badge.setStyleSheet(f"""
                background-color: {ACCENT_RED};
                color: #ffffff;
                font-size: 10px;
                font-weight: 800;
                padding: 3px 10px;
                border-radius: 12px;
                letter-spacing: 0.5px;
            """)
            self.lbl_status_icon.setText("✕")
            self.lbl_status_icon.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {ACCENT_RED}; background: transparent;")
        else:
            self.lbl_badge.setText(t("badge_queued"))
            self.lbl_badge.setStyleSheet(f"""
                background-color: {TEXT_FAINT};
                color: #ffffff;
                font-size: 10px;
                font-weight: 800;
                padding: 3px 10px;
                border-radius: 12px;
                letter-spacing: 0.5px;
            """)
            self.lbl_status_icon.setText("○")
            self.lbl_status_icon.setStyleSheet(f"font-size: 14px; color: {TEXT_FAINT}; background: transparent;")

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
            
        # Do not increment elapsed time while waiting in the queue
        if self.current_status == "PENDING":
            return

        # Elapsed Time
        self.elapsed_seconds += 1
        emins, esecs = divmod(self.elapsed_seconds, 60)
        self.tag_elapsed.setText(t("time_ms_format", mins=emins, secs=esecs) if emins > 0 else t("time_s_format", secs=esecs))

        # ETA Logic (Cloud only)
        if self.mode == "Cloud (Kaggle)":
            if self.current_status in ["PENDING", "EXTRACTING", "UPLOADING"]:
                self.lbl_eta.setText(t("eta_calculating"))
            elif self.current_status in ["PROCESSING_CLOUD", "DOWNLOADING", "REMUXING"]:
                if not getattr(self, "eta_initialized", False):
                    # Initialize ETA when Kaggle actually starts processing (Adjusted to be more realistic)
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

        is_active = status in ["PENDING", "EXTRACTING", "UPLOADING", "PROCESSING_CLOUD", "PROCESSING_LOCAL", "DOWNLOADING", "REMUXING"]
        self.btn_abort.setVisible(is_active)

        if is_active and not self.timer.isActive():
            self.timer.start()

        if status == "COMPLETED":
            self.timer.stop()
            self._set_badge_style("completed")
            if self.mode == "Cloud (Kaggle)":
                self.lbl_eta.setVisible(False)
            self._raw_message = "Purification complete · Audio isolated"
            self.lbl_message.setText(t("msg_purification_complete"))
            self.progress.setVisible(False)
        elif status == "ABORTED":
            self.timer.stop()
            self._set_badge_style("aborted")
            if self.mode == "Cloud (Kaggle)":
                self.lbl_eta.setVisible(False)
            self._raw_message = "Job aborted"
            self.lbl_message.setText(t("msg_job_aborted"))
            self.progress.setVisible(False)
        elif status in ["ERROR", "FAILED"]:
            self.timer.stop()
            self._set_badge_style("failed")
            if self.mode == "Cloud (Kaggle)":
                self.lbl_eta.setVisible(False)
            self._raw_message = "Processing failed"
            self.lbl_message.setText(t("msg_processing_failed"))
            self.progress.setVisible(False)
        elif status == "PENDING":
            self._set_badge_style("queued")
            if self.mode == "Cloud (Kaggle)":
                self.lbl_eta.setVisible(True)
                self.lbl_eta.setText(t("eta_in_queue"))
            self._raw_message = "Waiting in queue..."
            self.lbl_message.setText(t("msg_waiting_queue"))
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
        else:
            self._set_badge_style("running")
            if self.mode == "Cloud (Kaggle)":
                self.lbl_eta.setVisible(True)
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
            if not self._raw_message or self._raw_message == "Waiting in queue...":
                self._raw_message = "Isolating vocals with AI..."
                self.lbl_message.setText(t("msg_isolating_vocals"))

    def update_message(self, message: str):
        self._raw_message = message
        self.lbl_message.setText(translate_worker_message(message))

    def update_state(self, job_data: dict):
        """Update widget presentation state from a job dictionary."""
        self.job_dict = job_data
        if "duration" in job_data:
            self.duration = job_data["duration"]
        if "status" in job_data:
            self.update_status(job_data["status"])
        if "message" in job_data:
            self.update_message(job_data["message"])

    def retranslate_ui(self):
        """Dynamically refreshes text and tooltips when application language changes."""
        model_name = self.job_dict.get("model") or ("Kaggle T4" if "Cloud" in self.mode else "RoFormer")
        mode_prefix = t("tag_mode_cloud") if "Cloud" in self.mode else t("tag_mode_local")
        self.tag_engine.setText(f"{mode_prefix} · {model_name}")

        self.btn_abort.setText(t("btn_abort"))
        self.btn_delete.retranslate_ui()

        self._set_badge_style(self.current_badge_state)

        emins, esecs = divmod(self.elapsed_seconds, 60)
        self.tag_elapsed.setText(t("time_ms_format", mins=emins, secs=esecs) if emins > 0 else t("time_s_format", secs=esecs))

        if self._raw_message:
            self.lbl_message.setText(translate_worker_message(self._raw_message))

        if self.mode == "Cloud (Kaggle)" and self.lbl_eta.isVisible():
            if self.current_status == "PENDING":
                self.lbl_eta.setText(t("eta_in_queue"))
            elif self.current_status in ["EXTRACTING", "UPLOADING"]:
                self.lbl_eta.setText(t("eta_calculating"))
            elif self.remaining_seconds > 0:
                mins, secs = divmod(self.remaining_seconds, 60)
                self.lbl_eta.setText(t("eta_time_ms", mins=mins, secs=secs) if mins > 0 else t("eta_time_s", secs=secs))
            elif getattr(self, "eta_initialized", False):
                self.lbl_eta.setText(t("eta_anytime"))
