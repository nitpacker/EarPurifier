import re
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

try:
    from dependency_manager import DependencyManager
except ImportError:
    from src.dependency_manager import DependencyManager


# ─── 3-Zone Compact Audio Track Card Presentation View ────────────────────────

# ─── Model & Stage ETA Estimators ─────────────────────────────────────────────

def get_local_model_rtf(model_name: str, has_gpu: bool) -> tuple[float, float]:
    """Returns (rtf_multiplier, warmup_seconds) for local hardware execution."""
    m = (model_name or "").lower()
    if has_gpu:
        if "kim" in m:
            return 0.15, 12.0
        elif "mdx" in m:
            return 0.30, 15.0
        elif "roformer" in m:
            return 0.75, 18.0
        return 0.30, 15.0
    else:
        # Local CPU inference
        if "kim" in m:
            return 1.10, 22.0
        elif "mdx" in m:
            return 2.50, 28.0
        elif "roformer" in m:
            return 5.50, 35.0
        return 2.50, 28.0


def compute_local_stage_estimates(duration: float, model_name: str, has_gpu: bool) -> dict[str, float]:
    """Computes empirical duration estimates (in seconds) for local pipeline stages."""
    d = max(0.0, float(duration))
    rtf, warmup = get_local_model_rtf(model_name, has_gpu)
    t_extract = max(3.0, min(30.0, 3.0 + d * 0.005))
    t_infer = rtf * d
    t_remux = max(5.0, min(45.0, 5.0 + d * 0.010))
    return {
        "EXTRACTING": t_extract,
        "WARMUP": warmup,
        "INFERENCE": t_infer,
        "REMUXING": t_remux,
        "TOTAL": t_extract + warmup + t_infer + t_remux,
    }

def get_model_rtf(model_name: str) -> tuple[float, float]:
    """Returns (rtf_multiplier, overhead_seconds) based on model architecture."""
    m = (model_name or "").lower()
    if "kim" in m:
        # Kim Vocal 2: Fast ONNX model (~7.5x real-time on T4)
        return 0.135, 45.0
    elif "mdx" in m:
        # MDX23C: PyTorch STFT ConvNet (~3.7x real-time on T4)
        return 0.270, 50.0
    elif "roformer" in m:
        # Band-Split RoFormer: PyTorch Transformer (~1.45x real-time on T4)
        return 0.680, 55.0
    # Default fallback to MDX23C baseline
    return 0.270, 50.0


def compute_stage_estimates(duration: float, model_name: str) -> dict[str, float]:
    """Computes empirical duration estimates (in seconds) for each pipeline stage."""
    d = max(0.0, float(duration))
    rtf, overhead = get_model_rtf(model_name)

    t_extract = max(3.0, min(30.0, 3.0 + d * 0.005))
    t_upload = max(20.0, min(90.0, 20.0 + d * 0.015))
    t_cloud = overhead + (rtf * d)
    t_download = max(8.0, min(60.0, 8.0 + d * 0.008))
    t_remux = max(5.0, min(45.0, 5.0 + d * 0.010))

    return {
        "EXTRACTING": t_extract,
        "UPLOADING": t_upload,
        "PROCESSING_CLOUD": t_cloud,
        "DOWNLOADING": t_download,
        "REMUXING": t_remux,
        "PROCESSING_LOCAL": max(15.0, t_extract + (rtf * d)),
    }


def format_eta_time(seconds: int) -> str:
    """Formats remaining seconds into localized ETA string with hour support."""
    secs = max(0, int(seconds))
    if secs == 0:
        return t("eta_anytime")

    hrs, rem = divmod(secs, 3600)
    mins, s = divmod(rem, 60)

    if hrs > 0:
        return t("eta_time_hms", hours=hrs, mins=mins)
    elif mins > 0:
        return t("eta_time_ms", mins=mins, secs=s)
    else:
        return t("eta_time_s", secs=s)


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
        self.stage_elapsed = 0
        self.last_stage = None
        self._last_pct = -1
        self.eta_initialized = False
        self.is_cloud_congested = False
        self._congested_mins = 2
        self._raw_message = ""
        self._theme_mode = Theme.get_mode()
        self._infer_start_time = None
        self._infer_baseline_time = 0.0
        self._t_remux = 0.0
        self._stage_start_time = None

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

    @staticmethod
    def _format_elapsed(seconds: int) -> str:
        secs = max(0, int(seconds))
        hrs, rem = divmod(secs, 3600)
        mins, s = divmod(rem, 60)
        return f"{hrs:02d}:{mins:02d}:{s:02d}" if hrs > 0 else f"{mins:02d}:{s:02d}"

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

        # Total Processing Time (Elapsed Time) Slot
        if self.job_dict.get("status", "PENDING") == "PENDING":
            dur_txt = "00:00"
        else:
            dur_txt = self._format_elapsed(self.job_dict.get("final_elapsed_seconds", self.elapsed_seconds))
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
            font-weight: 600;
            color: {text_muted};
            background: transparent;
        """)

        for s in [self.sep1, self.sep2, self.sep3]:
            s.setStyleSheet(f"color: {text_faint}; font-family: {mono_font}; font-size: 11px; background: transparent;")

        self._update_model_label()

        self.lbl_name.setStyleSheet(f"font-weight: 700; font-size: 12.5px; color: {text_head}; background: transparent;")
        self.lbl_elapsed.setVisible(False)
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
        tokens = {
            "running": (t("badge_running"), "rgba(2, 132, 199, 0.12)", Theme.get_token("ACCENT_BLUE", mode), "rgba(2, 132, 199, 0.3)"),
            "completed": (t("badge_completed"), "rgba(16, 185, 129, 0.12)", Theme.get_token("ACCENT_EMERALD", mode), "rgba(16, 185, 129, 0.3)"),
            "aborted": (t("badge_aborted"), "rgba(245, 158, 11, 0.12)", Theme.get_token("ACCENT_AMBER", mode), "rgba(245, 158, 11, 0.3)"),
            "failed": (t("badge_failed"), "rgba(239, 68, 68, 0.12)", Theme.get_token("ACCENT_RED", mode), "rgba(239, 68, 68, 0.3)"),
        }
        text, bg, col, border = tokens.get(state, (t("badge_queued"), "rgba(134, 161, 147, 0.12)", Theme.get_token("TEXT_FAINT", mode), "rgba(134, 161, 147, 0.3)"))
        self.lbl_badge.setText(text)
        self.lbl_badge.setStyleSheet(f"background-color: {bg}; color: {col}; border: 1px solid {border}; font-size: 10px; font-weight: 800; padding: 1px 7px; border-radius: 10px;")

    def _recalculate_eta_on_stage_change(self, status: str):
        """Dynamically calculates remaining seconds upon pipeline stage transitions."""
        if self.duration <= 0.0:
            self.lbl_eta.setText(t("eta_calculating"))
            return

        model_name = self.job_dict.get("model") or ""

        if "Cloud" in self.mode:
            estimates = compute_stage_estimates(self.duration, model_name)
            cloud_stages = ["EXTRACTING", "UPLOADING", "PROCESSING_CLOUD", "DOWNLOADING", "REMUXING"]
            if status in cloud_stages:
                idx = cloud_stages.index(status)
                expected_remaining = int(round(sum(estimates[st] for st in cloud_stages[idx:])))
                if status in ["DOWNLOADING", "REMUXING"]:
                    self.remaining_seconds = min(self.remaining_seconds, expected_remaining) if self.remaining_seconds > 0 else expected_remaining
                elif not getattr(self, "eta_initialized", False):
                    self.remaining_seconds = expected_remaining
                    self.eta_initialized = True
                else:
                    self.remaining_seconds = min(self.remaining_seconds, expected_remaining) if self.remaining_seconds > 0 else expected_remaining
                self.lbl_eta.setText(format_eta_time(self.remaining_seconds))
            elif status == "PENDING":
                self.lbl_eta.setText(t("eta_in_queue"))
        else:
            has_gpu = DependencyManager.has_nvidia_gpu() if hasattr(DependencyManager, "has_nvidia_gpu") else False
            local_est = compute_local_stage_estimates(self.duration, model_name, has_gpu)
            if status == "EXTRACTING":
                rem = int(round(local_est["EXTRACTING"] + local_est["WARMUP"] + local_est["INFERENCE"] + local_est["REMUXING"]))
                self.remaining_seconds = rem
                self.eta_initialized = True
                self.lbl_eta.setText(format_eta_time(self.remaining_seconds))
            elif status == "PROCESSING_LOCAL":
                import time
                self._stage_start_time = time.time()
                self._infer_start_time = None
                self._infer_baseline_time = local_est["INFERENCE"]
                self._t_remux = local_est["REMUXING"]
                rem = int(round(local_est["WARMUP"] + local_est["INFERENCE"] + local_est["REMUXING"]))
                self.remaining_seconds = rem
                self.eta_initialized = True
                self.lbl_eta.setText(format_eta_time(self.remaining_seconds))
            elif status == "REMUXING":
                rem = int(round(local_est["REMUXING"]))
                self.remaining_seconds = min(self.remaining_seconds, rem) if self.remaining_seconds > 0 else rem
                self.lbl_eta.setText(format_eta_time(self.remaining_seconds))
            elif status == "PENDING":
                self.lbl_eta.setText(t("eta_in_queue"))

    def set_cloud_congested(self, congested: bool, mins: int = 2):
        self.is_cloud_congested = congested
        self._congested_mins = mins
        mono_font = Theme.resolve_mono_font()
        if congested:
            accent_amber = Theme.get_token("ACCENT_AMBER", self._theme_mode)
            self.sep3.setVisible(True)
            self.lbl_eta.setVisible(True)
            self.lbl_eta.setStyleSheet(f"font-family: {mono_font}; font-size: 11px; font-weight: 700; color: {accent_amber}; background: transparent;")
            self.lbl_eta.setText(t("eta_cloud_congested", mins=mins))
        else:
            accent_blue = Theme.get_token("ACCENT_BLUE", self._theme_mode)
            self.lbl_eta.setStyleSheet(f"font-family: {mono_font}; font-size: 11px; font-weight: 700; color: {accent_blue}; background: transparent;")
            self.lbl_eta.setText(format_eta_time(self.remaining_seconds))

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
        self.stage_elapsed += 1
        self.lbl_meta_dur.setText(self._format_elapsed(self.elapsed_seconds))

        if self.is_cloud_congested:
            self.lbl_eta.setText(t("eta_cloud_congested", mins=self._congested_mins))
            return

        if self.duration <= 0.0:
            self.lbl_eta.setText(t("eta_calculating"))
            return

        if not getattr(self, "eta_initialized", False):
            self._recalculate_eta_on_stage_change(self.current_status)

        if "Local" in self.mode and self.current_status == "PROCESSING_LOCAL" and getattr(self, "_infer_start_time", None) is None:
            min_floor = max(5, int(round(getattr(self, "_infer_baseline_time", 0.0) + getattr(self, "_t_remux", 5.0))))
            if self.remaining_seconds > min_floor:
                self.remaining_seconds -= 1
        else:
            if self.remaining_seconds > 0:
                self.remaining_seconds -= 1

        self.lbl_eta.setText(format_eta_time(self.remaining_seconds))

    def update_status(self, status: str):
        if status != self.current_status:
            self.last_stage = self.current_status
            self.current_status = status
            self.stage_elapsed = 0
            if status in ["EXTRACTING", "UPLOADING", "PROCESSING_CLOUD", "PROCESSING_LOCAL", "DOWNLOADING", "REMUXING"]:
                self._recalculate_eta_on_stage_change(status)
        else:
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

        if status in ["COMPLETED", "ABORTED", "ERROR", "FAILED"]:
            self.timer.stop()
            self.is_cloud_congested = False
            final_sec = self.job_dict.get("final_elapsed_seconds", self.elapsed_seconds)
            self.lbl_meta_dur.setText(self._format_elapsed(final_sec))
            if status == "COMPLETED":
                self.progress.setRange(0, 100)
                self.progress.setValue(100)
            self.progress.setVisible(False)
            self.lbl_elapsed.setVisible(False)

            if status == "COMPLETED":
                self._set_badge_style("completed")
                self.sep3.setVisible(True)
                self.lbl_eta.setVisible(True)
                self.lbl_eta.setStyleSheet(f"font-family: {mono_font}; font-size: 11px; font-weight: 700; color: {accent_emerald}; background: transparent;")
                self.lbl_eta.setText(t("meta_saved_to_output"))
                self._raw_message = "Purification complete · Audio isolated"
                self.lbl_message.setText(t("msg_purification_complete"))
                self.lbl_message.setStyleSheet(f"font-size: 11px; font-weight: 500; color: {text_muted}; background: transparent;")
                self.btn_show_folder.setVisible(True)
            elif status == "ABORTED":
                self._set_badge_style("aborted")
                self.sep3.setVisible(False)
                self.lbl_eta.setVisible(False)
                self._raw_message = "Job aborted"
                self.lbl_message.setText(t("msg_job_aborted"))
                self.lbl_message.setStyleSheet(f"font-size: 11px; font-weight: 500; color: {accent_amber}; background: transparent;")
                self.btn_show_folder.setVisible(False)
            else:
                self._set_badge_style("failed")
                self.sep3.setVisible(False)
                self.lbl_eta.setVisible(False)
                self._raw_message = "Processing failed"
                self.lbl_message.setText(t("msg_processing_failed"))
                self.lbl_message.setStyleSheet(f"font-size: 11px; font-weight: 500; color: {accent_red}; background: transparent;")
                self.btn_show_folder.setVisible(False)

        elif status == "PENDING":
            self.lbl_meta_dur.setText("00:00")
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
            self.lbl_meta_dur.setText(self._format_elapsed(self.elapsed_seconds))
            if not self.is_cloud_congested:
                self.sep3.setVisible(True)
                self.lbl_eta.setVisible(True)
                self.lbl_eta.setStyleSheet(f"font-family: {mono_font}; font-size: 11px; font-weight: 700; color: {accent_blue}; background: transparent;")
            self.progress.setVisible(True)
            if "Local" in self.mode:
                self.progress.setRange(0, 100)
                if status == "EXTRACTING":
                    self.progress.setValue(max(self.progress.value(), 5))
                elif status == "PROCESSING_LOCAL":
                    self.progress.setValue(max(self.progress.value(), 10))
                elif status == "REMUXING":
                    self.progress.setValue(max(self.progress.value(), 90))
            else:
                self.progress.setRange(0, 0)
            self.lbl_elapsed.setVisible(False)
            self.btn_show_folder.setVisible(False)
            if not self._raw_message or self._raw_message == "Waiting in queue...":
                self._raw_message = "Isolating vocals with AI..."
                self.lbl_message.setText(t("msg_isolating_vocals"))
            self.lbl_message.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {accent_emerald}; background: transparent;")

    def update_message(self, message: str):
        if self.current_status in ["COMPLETED", "ABORTED", "ERROR", "FAILED"]:
            return

        if message.startswith("QUEUE_CONGESTED:"):
            try:
                mins = int(message.split(":", 1)[1])
            except Exception:
                mins = 2
            self.set_cloud_congested(True, mins)
            return
        elif message == "QUEUE_RESOLVED" or (self.is_cloud_congested and "running" in message.lower()):
            self.set_cloud_congested(False)
            if message == "QUEUE_RESOLVED":
                return

        # Scrape progress percentage in local mode for live progress bar and ETA updates
        if "Local" in self.mode and self.current_status == "PROCESSING_LOCAL":
            pass_match = re.search(r'\(Pass (\d+)/(\d+)\)\.\.\.\s*(\d{1,3})%', message)
            pct_match = re.search(r'(\d{1,3})%', message)
            p_infer = None
            global_pct = None

            if pass_match:
                pass_num = int(pass_match.group(1))
                pct = max(0, min(100, int(pass_match.group(3))))
                if pass_num == 1:
                    p_infer = (pct / 100.0) * 0.95
                    global_pct = 10.0 + (pct / 100.0) * 76.0
                else:
                    p_infer = 0.95 + (pct / 100.0) * 0.05
                    global_pct = 86.0 + (pct / 100.0) * 4.0
            elif pct_match:
                pct = max(0, min(100, int(pct_match.group(1))))
                p_infer = pct / 100.0
                global_pct = 10.0 + (pct / 100.0) * 80.0

            if global_pct is not None:
                try:
                    new_val = max(self.progress.value(), int(round(global_pct)))
                    self.progress.setRange(0, 100)
                    self.progress.setValue(min(90, new_val))
                    self._last_pct = new_val

                    import time
                    now = time.time()
                    if getattr(self, "_infer_start_time", None) is None:
                        stage_dur = now - getattr(self, "_stage_start_time", now)
                        if self.stage_elapsed > 0 and stage_dur < 1.0:
                            self._infer_start_time = now - float(self.stage_elapsed)
                        else:
                            self._infer_start_time = now
                        baseline_rem = getattr(self, "_infer_baseline_time", 0.0) + getattr(self, "_t_remux", 10.0)
                        if baseline_rem > 0:
                            self.remaining_seconds = int(round(baseline_rem))
                            self.lbl_eta.setText(format_eta_time(self.remaining_seconds))

                    delta_t = max(0.1, now - self._infer_start_time)
                    if p_infer is not None and p_infer >= 0.03 and delta_t >= 2.0:
                        r_obs = p_infer / delta_t
                        t_base = getattr(self, "_infer_baseline_time", 0.0)
                        if t_base <= 0.0 and self.duration > 0.0:
                            has_gpu = DependencyManager.has_nvidia_gpu() if hasattr(DependencyManager, "has_nvidia_gpu") else False
                            local_est = compute_local_stage_estimates(self.duration, self.job_dict.get("model", ""), has_gpu)
                            t_base = local_est["INFERENCE"]
                            self._infer_baseline_time = t_base
                            self._t_remux = local_est["REMUXING"]

                        r_base = 1.0 / max(1.0, t_base)
                        beta = min(0.85, 0.2 + 0.65 * p_infer)
                        r_eff = beta * r_obs + (1.0 - beta) * r_base
                        if r_eff > 0:
                            rem_infer = (1.0 - p_infer) / r_eff
                            t_remux = getattr(self, "_t_remux", 10.0)
                            new_eta = max(5, int(round(rem_infer + t_remux)))
                            self.remaining_seconds = new_eta
                            self.lbl_eta.setText(format_eta_time(self.remaining_seconds))
                except Exception:
                    pass

        self._raw_message = message
        self.lbl_message.setText(translate_worker_message(message))

    def update_state(self, job_data: dict):
        self.job_dict = job_data
        duration_updated = False
        if "duration" in job_data and job_data["duration"] > 0:
            if self.duration != job_data["duration"]:
                self.duration = job_data["duration"]
                duration_updated = True
        if "final_elapsed_seconds" in job_data:
            self.elapsed_seconds = int(job_data["final_elapsed_seconds"])
            self.lbl_meta_dur.setText(self._format_elapsed(self.elapsed_seconds))
        if "status" in job_data and job_data["status"] != self.current_status:
            self.update_status(job_data["status"])
        elif duration_updated and self.current_status in ["EXTRACTING", "UPLOADING", "PROCESSING_CLOUD", "PROCESSING_LOCAL"]:
            self._recalculate_eta_on_stage_change(self.current_status)
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
        if self.is_cloud_congested:
            self.lbl_eta.setText(t("eta_cloud_congested", mins=self._congested_mins))
        elif self.current_status == "PENDING":
            self.lbl_eta.setText(t("eta_in_queue"))
        elif self.current_status == "COMPLETED":
            self.lbl_eta.setText(t("meta_saved_to_output"))
        elif self.current_status in ["EXTRACTING", "UPLOADING", "PROCESSING_CLOUD", "PROCESSING_LOCAL", "DOWNLOADING", "REMUXING"]:
            if self.duration <= 0.0:
                self.lbl_eta.setText(t("eta_calculating"))
            else:
                self.lbl_eta.setText(format_eta_time(self.remaining_seconds))
