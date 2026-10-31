import os
import webbrowser
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QFrame, QListWidget, QListWidgetItem, QMessageBox
)
from PySide6.QtCore import Qt, Signal

from .theme import (
    CARD_BORDER, CARD_BORDER_HOVER,
    TEXT_HEAD, TEXT_BODY, TEXT_MUTED,
    ACCENT_EMERALD, ACCENT_BLUE, ACCENT_RED,
    get_scrollbar_qss, get_combobox_qss, get_primary_button_qss
)
from .components import StatusGroupHeader
from .dialogs import DeleteConfirmDialog
from .job_widget import JobWidget

try:
    from queue_manager import QueueManager
    from config_manager import ConfigManager
except ImportError:
    from src.queue_manager import QueueManager
    from src.config_manager import ConfigManager


# ─── Job Queue Section (Reusable Engine Canvas) ───────────────────────────────

class JobQueueSection(QWidget):
    add_media_clicked = Signal()
    add_video_clicked = add_media_clicked
    download_model_clicked = Signal(str, str)

    def __init__(self, mode: str, queue_manager: QueueManager, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.queue_manager = queue_manager
        self.config = config
        self.selection_mode = False
        self.job_widgets: dict[str, JobWidget] = {}

        self.init_ui()
        self.refresh_list()
        self.update_model_button_state()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 18, 24, 18)
        main_layout.setSpacing(14)

        # ── 1. Top Section Header (Breadcrumbs + Primary Action Button) ──
        header_bar = QHBoxLayout()
        header_bar.setSpacing(12)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        engine_name = "Cloud Engine (Kaggle T4)" if "Cloud" in self.mode else "Local Engine (Hardware GPU)"
        subtitle_text = "Free Cloud GPUs · 30-Second Dataset Sync" if "Cloud" in self.mode else "High-Speed Local Inference · RoFormer AI"

        bread_row = QHBoxLayout()
        bread_row.setSpacing(6)
        bread_dot = QLabel("●")
        bread_dot.setStyleSheet(f"color: {ACCENT_EMERALD}; font-size: 13px; background: transparent;")
        bread_row.addWidget(bread_dot)

        lbl_engine = QLabel(engine_name)
        lbl_engine.setStyleSheet(f"font-size: 18px; font-weight: 800; color: {TEXT_HEAD}; background: transparent;")
        bread_row.addWidget(lbl_engine)
        bread_row.addStretch()
        title_box.addLayout(bread_row)

        self.lbl_sub = QLabel(subtitle_text)
        self.lbl_sub.setStyleSheet(f"font-size: 12px; color: {TEXT_MUTED}; font-weight: 500; background: transparent;")
        title_box.addWidget(self.lbl_sub)
        header_bar.addLayout(title_box)

        header_bar.addStretch()

        # Primary Action Button: '+ Add Media' (Sprout-Teal Gradient)
        self.btn_add = QPushButton("＋ Add Media")
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.setStyleSheet(get_primary_button_qss())
        self.btn_add.clicked.connect(self._on_add_clicked)
        header_bar.addWidget(self.btn_add)

        # Select to Delete (Ghost Button)
        self.btn_select_mode = QPushButton("Select to Delete")
        self.btn_select_mode.setCursor(Qt.PointingHandCursor)
        self.btn_select_mode.setStyleSheet(f"""
            QPushButton {{
                background-color: #ffffff;
                color: {TEXT_BODY};
                border: 1px solid {CARD_BORDER};
                padding: 8px 14px;
                border-radius: 7px;
                font-weight: 600;
                font-size: 12px;
            }}
            QPushButton:hover {{
                border-color: {ACCENT_EMERALD};
                color: {ACCENT_EMERALD};
                background-color: #f0fdf4;
            }}
        """)
        self.btn_select_mode.clicked.connect(self.toggle_selection_mode)
        header_bar.addWidget(self.btn_select_mode)

        # Clear History (Ghost Red Button)
        self.btn_clear_history = QPushButton("Clear History")
        self.btn_clear_history.setCursor(Qt.PointingHandCursor)
        self.btn_clear_history.setStyleSheet(f"""
            QPushButton {{
                background-color: #ffffff;
                color: {ACCENT_RED};
                border: 1px solid #fecaca;
                padding: 8px 14px;
                border-radius: 7px;
                font-weight: 600;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: #fef2f2;
                border-color: {ACCENT_RED};
            }}
        """)
        self.btn_clear_history.clicked.connect(self.on_clear_history)
        header_bar.addWidget(self.btn_clear_history)

        main_layout.addLayout(header_bar)

        # ── 2. Fully Styled Modern Dropdown (NO 1990s BEVELS!) ──
        views_bar = QHBoxLayout()
        views_bar.setSpacing(8)

        lbl_view = QLabel("Filter:")
        lbl_view.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; font-weight: 700; background: transparent;")
        views_bar.addWidget(lbl_view)

        self.cmb_filter = QComboBox()
        self.cmb_filter.addItems(["All Jobs", "In Progress", "Completed"])
        self.cmb_filter.setStyleSheet(get_combobox_qss())
        self.cmb_filter.currentIndexChanged.connect(self.refresh_list)
        views_bar.addWidget(self.cmb_filter)

        views_bar.addStretch()
        
        btn_mariam = QPushButton("🌱 From Mariam Initiative")
        btn_mariam.setCursor(Qt.PointingHandCursor)
        btn_mariam.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #10b981;
                font-weight: 700;
                font-size: 12px;
                border: none;
                text-align: right;
            }
            QPushButton:hover {
                color: #047857;
                text-decoration: underline;
            }
        """)
        btn_mariam.clicked.connect(lambda: webbrowser.open('https://t.me/MariamInitiative'))
        views_bar.addWidget(btn_mariam)

        main_layout.addLayout(views_bar)

        # ── 3. Batch Action Bar ──
        self.batch_bar = QFrame()
        self.batch_bar.setStyleSheet("""
            QFrame {
                background-color: #ecfdf5;
                border: 1px solid #a7f3d0;
                border-radius: 8px;
            }
        """)
        batch_layout = QHBoxLayout(self.batch_bar)
        batch_layout.setContentsMargins(14, 8, 14, 8)
        batch_layout.setSpacing(10)

        self.lbl_selected_count = QLabel("0 jobs selected")
        self.lbl_selected_count.setStyleSheet(f"color: {ACCENT_EMERALD}; font-weight: 800; font-size: 12px; background: transparent;")
        batch_layout.addWidget(self.lbl_selected_count)

        batch_layout.addStretch()

        btn_select_all = QPushButton("Select All")
        btn_select_all.setCursor(Qt.PointingHandCursor)
        btn_select_all.setStyleSheet(f"""
            QPushButton {{
                background-color: #ffffff;
                border: 1px solid {CARD_BORDER};
                color: {TEXT_BODY};
                padding: 5px 14px;
                border-radius: 5px;
                font-weight: 600;
                font-size: 11px;
            }}
            QPushButton:hover {{
                border-color: {ACCENT_EMERALD};
                color: {ACCENT_EMERALD};
            }}
        """)
        btn_select_all.clicked.connect(self.on_select_all)
        batch_layout.addWidget(btn_select_all)

        btn_cancel_select = QPushButton("Cancel")
        btn_cancel_select.setCursor(Qt.PointingHandCursor)
        btn_cancel_select.setStyleSheet(f"""
            QPushButton {{
                background-color: #ffffff;
                border: 1px solid {CARD_BORDER};
                color: {TEXT_BODY};
                padding: 5px 14px;
                border-radius: 5px;
                font-weight: 600;
                font-size: 11px;
            }}
            QPushButton:hover {{
                border-color: {CARD_BORDER_HOVER};
            }}
        """)
        btn_cancel_select.clicked.connect(self.toggle_selection_mode)
        batch_layout.addWidget(btn_cancel_select)

        btn_delete_selected = QPushButton("Remove Selected")
        btn_delete_selected.setCursor(Qt.PointingHandCursor)
        btn_delete_selected.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT_RED};
                color: #ffffff;
                font-weight: 700;
                padding: 5px 16px;
                border-radius: 5px;
                border: none;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: #dc2626;
            }}
        """)
        btn_delete_selected.clicked.connect(self.on_delete_selected)
        batch_layout.addWidget(btn_delete_selected)

        self.batch_bar.setVisible(False)
        main_layout.addWidget(self.batch_bar)

        # ── 4. Job List Canvas ──
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
                outline: 0px;
            }}
            QListWidget::item {{
                background: transparent;
                border: none;
                padding: 0px;
                margin-bottom: 6px;
            }}
            {get_scrollbar_qss()}
        """)
        main_layout.addWidget(self.list_widget, 1)

    def refresh_list(self):
        self.list_widget.clear()
        self.job_widgets.clear()

        jobs = self.queue_manager.get_all_jobs()
        filter_idx = self.cmb_filter.currentIndex()

        sorted_jobs = sorted(jobs.items(), key=lambda x: x[1].get("added_at", ""))

        active_jobs = []
        completed_jobs = []

        for jid, job in sorted_jobs:
            if job.get("mode", "Cloud (Kaggle)") != self.mode:
                continue

            status = job.get("status", "PENDING")
            is_active = status in ["PENDING", "EXTRACTING", "UPLOADING", "PROCESSING_CLOUD", "PROCESSING_LOCAL", "DOWNLOADING", "REMUXING"]
            is_completed = status in ["COMPLETED", "ERROR", "ABORTED"]

            if filter_idx == 1 and not is_active:
                continue
            if filter_idx == 2 and not is_completed:
                continue

            if is_active:
                active_jobs.append((jid, job))
            else:
                completed_jobs.append((jid, job))

        if active_jobs:
            hdr_active = StatusGroupHeader("In Progress", len(active_jobs), ACCENT_BLUE)
            item_hdr = QListWidgetItem()
            item_hdr.setSizeHint(hdr_active.sizeHint())
            item_hdr.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(item_hdr)
            self.list_widget.setItemWidget(item_hdr, hdr_active)

            for jid, job in active_jobs:
                self.add_job_widget(jid, job)

        if completed_jobs:
            hdr_comp = StatusGroupHeader("Completed", len(completed_jobs), ACCENT_EMERALD)
            item_hdr = QListWidgetItem()
            item_hdr.setSizeHint(hdr_comp.sizeHint())
            item_hdr.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(item_hdr)
            self.list_widget.setItemWidget(item_hdr, hdr_comp)

            for jid, job in completed_jobs:
                self.add_job_widget(jid, job)

        if not active_jobs and not completed_jobs:
            empty_widget = QWidget()
            empty_layout = QVBoxLayout(empty_widget)
            empty_layout.setAlignment(Qt.AlignCenter)
            empty_layout.setContentsMargins(40, 60, 40, 60)
            empty_layout.setSpacing(12)

            lbl_empty_icon = QLabel("🌱")
            lbl_empty_icon.setStyleSheet("font-size: 38px; background: transparent;")
            lbl_empty_icon.setAlignment(Qt.AlignCenter)
            empty_layout.addWidget(lbl_empty_icon)

            lbl_empty_title = QLabel("No tasks in this queue")
            lbl_empty_title.setStyleSheet(f"font-size: 15px; font-weight: 800; color: {TEXT_HEAD}; background: transparent;")
            lbl_empty_title.setAlignment(Qt.AlignCenter)
            empty_layout.addWidget(lbl_empty_title)

            lbl_empty_desc = QLabel("Click '+ Add Media' above to upload media files and isolate vocals with AI.")
            lbl_empty_desc.setStyleSheet(f"font-size: 12.5px; color: {TEXT_MUTED}; background: transparent;")
            lbl_empty_desc.setAlignment(Qt.AlignCenter)
            empty_layout.addWidget(lbl_empty_desc)

            item = QListWidgetItem()
            item.setSizeHint(empty_widget.sizeHint())
            item.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, empty_widget)

        self.update_counts()

    def add_job_widget(self, jid: str, job: dict):
        widget = JobWidget(jid, job, mode=self.mode)
        widget.update_status(job.get("status", "PENDING"))
        widget.set_selection_mode(self.selection_mode)

        widget.sig_delete_clicked.connect(self.on_delete_single)
        widget.sig_abort_clicked.connect(self.on_abort_job)
        widget.sig_selection_toggled.connect(lambda _jid, _chk: self.update_selected_count())

        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, widget)

        self.job_widgets[jid] = widget

    def update_counts(self):
        jobs = self.queue_manager.get_all_jobs()
        mode_jobs = [j for j in jobs.values() if j.get("mode", "Cloud (Kaggle)") == self.mode]
        active_count = sum(1 for j in mode_jobs if j.get("status") in ["PENDING", "EXTRACTING", "UPLOADING", "PROCESSING_CLOUD", "PROCESSING_LOCAL", "DOWNLOADING", "REMUXING"])
        completed_count = sum(1 for j in mode_jobs if j.get("status") in ["COMPLETED", "ERROR", "ABORTED"])

        self.cmb_filter.blockSignals(True)
        idx = self.cmb_filter.currentIndex()
        self.cmb_filter.setItemText(0, f"All Jobs ({len(mode_jobs)})")
        self.cmb_filter.setItemText(1, f"In Progress ({active_count})")
        self.cmb_filter.setItemText(2, f"Completed ({completed_count})")
        self.cmb_filter.setCurrentIndex(idx)
        self.cmb_filter.blockSignals(False)

    def toggle_selection_mode(self):
        self.selection_mode = not self.selection_mode
        self.batch_bar.setVisible(self.selection_mode)
        self.btn_select_mode.setText("Exit Selection" if self.selection_mode else "Select to Delete")

        for widget in self.job_widgets.values():
            widget.set_selection_mode(self.selection_mode)

        self.update_selected_count()

    def update_selected_count(self):
        count = sum(1 for w in self.job_widgets.values() if w.is_selected())
        self.lbl_selected_count.setText(f"{count} job(s) selected")

    def on_select_all(self):
        for widget in self.job_widgets.values():
            widget.set_selected(True)
        self.update_selected_count()

    def on_delete_single(self, job_id: str):
        dlg = DeleteConfirmDialog(1, self.config, self)
        if dlg.exec() == DeleteConfirmDialog.Accepted:
            self.queue_manager.delete_job(job_id, delete_output=dlg.should_delete_files())
            self.refresh_list()

    def on_delete_selected(self):
        selected_ids = [jid for jid, w in self.job_widgets.items() if w.is_selected()]
        if not selected_ids:
            QMessageBox.information(self, "No Selection", "Please select at least one job to delete.")
            return

        dlg = DeleteConfirmDialog(len(selected_ids), self.config, self)
        if dlg.exec() == DeleteConfirmDialog.Accepted:
            self.queue_manager.delete_jobs(selected_ids, delete_output=dlg.should_delete_files())
            self.toggle_selection_mode()
            self.refresh_list()

    def on_clear_history(self):
        jobs = self.queue_manager.get_all_jobs()
        history_jobs = [jid for jid, j in jobs.items() if j.get("mode", "Cloud (Kaggle)") == self.mode and j.get("status") in ["COMPLETED", "ERROR", "ABORTED"]]

        if not history_jobs:
            QMessageBox.information(self, "History Empty", "No completed, failed, or aborted jobs to clear.")
            return

        dlg = DeleteConfirmDialog(len(history_jobs), self.config, self)
        if dlg.exec() == DeleteConfirmDialog.Accepted:
            self.queue_manager.clear_history(self.mode, delete_output=dlg.should_delete_files())
            self.refresh_list()

    def on_abort_job(self, job_id: str):
        self.queue_manager.abort_job(job_id)
        if job_id in self.job_widgets:
            self.job_widgets[job_id].update_status("ABORTED")
            self.job_widgets[job_id].update_message("Aborted by user.")
        self.update_counts()

    def on_status_updated(self, job_id: str, status: str):
        if job_id in self.job_widgets:
            self.job_widgets[job_id].update_status(status)
        else:
            self.refresh_list()
        self.update_counts()

    def on_progress_updated(self, job_id: str, message: str):
        if job_id in self.job_widgets:
            self.job_widgets[job_id].update_message(message)

    def _get_selected_model_name(self) -> str:
        model_selection = self.config.get("local_model", "")
        if "RoFormer" in model_selection:
            return "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
        elif "MDX23C" in model_selection:
            return "MDX23C-8KFFT-InstVoc_HQ.ckpt"
        else:
            return "Kim_Vocal_2.onnx"

    def update_model_button_state(self):
        if "Local" not in self.mode:
            return
            
        model_name = self._get_selected_model_name()
        
        if "roformer" in model_name.lower():
            display_name = "Maximum Quality · RoFormer AI"
            size_txt = "~250 MB"
            subfolder = "RoFormer"
        elif "mdx23c" in model_name.lower():
            display_name = "Balanced Performance · MDX23C AI"
            size_txt = "~150 MB"
            subfolder = "MDX23C"
        else:
            display_name = "High-Speed Inference · Kim Vocal 2 AI"
            size_txt = "~110 MB"
            subfolder = "Kim_Vocal_2"
            
        self.lbl_sub.setText(display_name)
        
        # Download into subfolders
        models_dir = os.path.join(self.config.appdata_dir, "models", subfolder)
        model_path = os.path.join(models_dir, model_name)
        
        if os.path.exists(model_path):
            self.btn_add.setText("＋ Add Media")
            self._model_needs_download = False
        else:
            self.btn_add.setText(f"⬇ Download Model ({size_txt})")
            self._model_needs_download = True

    def _on_add_clicked(self):
        if "Local" in self.mode and getattr(self, "_model_needs_download", False):
            model_name = self._get_selected_model_name()
            subfolder = "RoFormer" if "roformer" in model_name.lower() else ("MDX23C" if "mdx23c" in model_name.lower() else "Kim_Vocal_2")
            self.download_model_clicked.emit(model_name, subfolder)
        else:
            self.add_media_clicked.emit()
