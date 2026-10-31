import os
import subprocess
import webbrowser
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFrame, QListWidget, QListWidgetItem, QMessageBox, QMenu
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction

from .theme import (
    Theme, ThemeMode,
    get_scrollbar_qss, get_primary_button_qss
)
from .components import StatusGroupHeader
from .queue_widgets import (
    SegmentedPillSwitcher, FloatingBatchDock, DropZoneWidget
)
from .dialogs import DeleteConfirmDialog
from .job_widget import JobWidget

try:
    from queue_manager import QueueManager
    from config_manager import ConfigManager
except ImportError:
    from src.queue_manager import QueueManager
    from src.config_manager import ConfigManager

try:
    from i18n import t, is_rtl, format_jobs_count
except ImportError:
    from src.i18n import t, is_rtl, format_jobs_count


# ─── Job Queue Section (Reusable Studio Canvas) ────────────────────────────────

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
        self.job_items: dict[str, QListWidgetItem] = {}
        self.dropzone_item: QListWidgetItem = None
        self.dropzone_widget: DropZoneWidget = None
        self._model_needs_download = False
        self._model_size_txt = "~250 MB"
        self._theme_mode = Theme.get_mode()

        self.init_ui()
        self.refresh_list()
        self.update_model_button_state()

    def _get_engine_title(self) -> str:
        return t("cloud_engine_title") if "Cloud" in self.mode else t("local_engine_title")

    def _get_engine_subtitle(self) -> str:
        return t("cloud_engine_sub") if "Cloud" in self.mode else t("local_engine_sub_default")

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 14, 20, 14)
        main_layout.setSpacing(10)

        # ── 1. Top Section Header ──
        header_bar = QHBoxLayout()
        header_bar.setSpacing(10)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        bread_row = QHBoxLayout()
        bread_row.setSpacing(6)
        self.bread_dot = QLabel("●")
        self.bread_dot.setStyleSheet(f"color: #10b981; font-size: 11px; background: transparent;")
        bread_row.addWidget(self.bread_dot)

        self.lbl_engine = QLabel(self._get_engine_title())
        self.lbl_engine.setStyleSheet("font-size: 16px; font-weight: 800; background: transparent;")
        bread_row.addWidget(self.lbl_engine)
        bread_row.addStretch()
        title_box.addLayout(bread_row)

        self.lbl_sub = QLabel(self._get_engine_subtitle())
        self.lbl_sub.setStyleSheet("font-size: 11.5px; font-weight: 500; background: transparent;")
        title_box.addWidget(self.lbl_sub)
        header_bar.addLayout(title_box)

        header_bar.addStretch()

        # Primary Action Button: '+ Add Media' (Sprout-Teal Gradient)
        self.btn_add = QPushButton(t("btn_add_media"))
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.setStyleSheet(get_primary_button_qss(self._theme_mode))
        self.btn_add.clicked.connect(self._on_add_clicked)
        header_bar.addWidget(self.btn_add)

        # Ghost Action Group (Select, Clear, Overflow ⋯)
        self.ghost_group = QFrame()
        self.ghost_group.setObjectName("ghostGroup")
        ghost_layout = QHBoxLayout(self.ghost_group)
        ghost_layout.setContentsMargins(4, 2, 4, 2)
        ghost_layout.setSpacing(4)

        # Select Button
        self.btn_select_mode = QPushButton(t("btn_select_mode"))
        self.btn_select_mode.setCursor(Qt.PointingHandCursor)
        self.btn_select_mode.clicked.connect(self.toggle_selection_mode)
        ghost_layout.addWidget(self.btn_select_mode)

        # Subtle Vertical Divider
        self.sep_ghost1 = QFrame()
        self.sep_ghost1.setObjectName("ghostDivider")
        self.sep_ghost1.setFrameShape(QFrame.VLine)
        self.sep_ghost1.setFixedHeight(14)
        ghost_layout.addWidget(self.sep_ghost1)

        # Clear History Button
        self.btn_clear_history = QPushButton(t("btn_clear_history"))
        self.btn_clear_history.setCursor(Qt.PointingHandCursor)
        self.btn_clear_history.clicked.connect(self.on_clear_history)
        ghost_layout.addWidget(self.btn_clear_history)

        header_bar.addWidget(self.ghost_group)
        main_layout.addLayout(header_bar)

        # Subtle Horizontal Divider Line (1px border separating header from filter bar)
        self.header_divider = QFrame()
        self.header_divider.setObjectName("headerDivider")
        self.header_divider.setFrameShape(QFrame.HLine)
        self.header_divider.setFixedHeight(1)
        main_layout.addWidget(self.header_divider)

        # ── 2. Filter Bar: Segmented Switcher & Link ──
        views_bar = QHBoxLayout()
        views_bar.setSpacing(8)

        self.lbl_view = QLabel(t("filter_label"))
        self.lbl_view.setStyleSheet("font-size: 11.5px; font-weight: 700; background: transparent;")
        views_bar.addWidget(self.lbl_view)

        # Segmented Capsule Switcher (replaces combobox)
        self.switcher = SegmentedPillSwitcher()
        self.switcher.currentIndexChanged.connect(self._apply_filter)
        views_bar.addWidget(self.switcher)

        views_bar.addStretch()

        self.btn_mariam = QPushButton(t("mariam_initiative"))
        self.btn_mariam.setCursor(Qt.PointingHandCursor)
        self.btn_mariam.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #10b981;
                font-weight: 700;
                font-size: 11.5px;
                border: none;
            }
            QPushButton:hover {
                color: #047857;
                text-decoration: underline;
            }
        """)
        self.btn_mariam.clicked.connect(lambda: webbrowser.open('https://t.me/MariamInitiative'))
        views_bar.addWidget(self.btn_mariam)

        main_layout.addLayout(views_bar)

        # ── 3. Job List Canvas (Scrollable) ──
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.NoSelection)
        self.list_widget.setFocusPolicy(Qt.NoFocus)
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
                outline: 0px;
            }}
            QListWidget::item, QListWidget::item:selected, QListWidget::item:hover, QListWidget::item:focus {{
                background: transparent;
                border: none;
                outline: none;
                padding: 0px;
                margin-bottom: 4px;
            }}
            {get_scrollbar_qss(self._theme_mode)}
        """)
        main_layout.addWidget(self.list_widget, 1)

        # ── 4. Floating Batch Action Dock (Anchored Overlay) ──
        self.batch_dock = FloatingBatchDock(self)
        self.batch_dock.sig_select_all.connect(self.on_select_all)
        self.batch_dock.sig_cancel.connect(self.toggle_selection_mode)
        self.batch_dock.sig_delete.connect(self.on_delete_selected)
        self.batch_dock.hide()

        self.apply_theme(self._theme_mode)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.batch_dock.isVisible():
            dock_w = min(440, self.width() - 32)
            dock_h = 42
            x = (self.width() - dock_w) // 2
            y = self.height() - dock_h - 14
            self.batch_dock.setGeometry(x, y, dock_w, dock_h)
            self.batch_dock.raise_()

    def apply_theme(self, theme_mode: str):
        self._theme_mode = theme_mode
        card_bg = Theme.get_token("CARD_BG", theme_mode)
        card_border = Theme.get_token("CARD_BORDER", theme_mode)
        text_head = Theme.get_token("TEXT_HEAD", theme_mode)
        text_body = Theme.get_token("TEXT_BODY", theme_mode)
        text_muted = Theme.get_token("TEXT_MUTED", theme_mode)
        accent = Theme.get_token("ACCENT_EMERALD", theme_mode)

        self.lbl_engine.setStyleSheet(f"font-size: 18px; font-weight: 800; color: {text_head}; background: transparent;")
        self.lbl_sub.setStyleSheet(f"font-size: 11.5px; font-weight: 500; color: {text_muted}; background: transparent;")
        self.lbl_view.setStyleSheet(f"font-size: 11.5px; font-weight: 700; color: {text_muted}; background: transparent;")

        if hasattr(self, 'header_divider'):
            self.header_divider.setStyleSheet(f"background-color: {card_border}; border: none; max-height: 1px; min-height: 1px;")

        self.btn_add.setStyleSheet(get_primary_button_qss(theme_mode))

        self.ghost_group.setStyleSheet(f"""
            QFrame#ghostGroup {{
                background-color: {card_bg};
                border: 1px solid {card_border};
                border-radius: 8px;
            }}
            QFrame#ghostDivider {{
                background-color: {card_border};
                border: none;
                width: 1px;
            }}
            QPushButton {{
                background: transparent;
                color: {text_body};
                font-weight: 600;
                font-size: 11.5px;
                padding: 5px 10px;
                border-radius: 5px;
                border: none;
            }}
            QPushButton:hover {{
                color: {accent};
                background: rgba(16, 185, 129, 0.08);
            }}
        """)

        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
                outline: 0px;
            }}
            QListWidget::item, QListWidget::item:selected, QListWidget::item:hover, QListWidget::item:focus {{
                background: transparent;
                border: none;
                outline: none;
                padding: 0px;
                margin-bottom: 4px;
            }}
            {get_scrollbar_qss(theme_mode)}
        """)

        self.switcher.update_style()
        self.batch_dock.update_style()

        for widget in self.job_widgets.values():
            widget.apply_theme(theme_mode)

    def _open_output_folder(self):
        try:
            out_dir = self.config.get_output_folder(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            if os.path.exists(out_dir):
                os.startfile(out_dir)
        except Exception:
            pass

    def on_open_folder_for_job(self, job_id: str):
        job = self.queue_manager.get_job(job_id)
        if not job:
            return
        out_media = job.get("output_media") or job.get("output_video")
        if out_media and os.path.exists(out_media):
            try:
                subprocess.run(["explorer.exe", "/select,", os.path.normpath(out_media)])
            except Exception:
                try:
                    os.startfile(os.path.dirname(out_media))
                except Exception:
                    pass
        else:
            self._open_output_folder()

    def _apply_filter(self):
        filter_idx = self.switcher.current_index

        for jid, widget in self.job_widgets.items():
            item = self.job_items.get(jid)
            if not item:
                continue
            status = widget.current_status
            is_active = status in ["PENDING", "EXTRACTING", "UPLOADING", "PROCESSING_CLOUD", "PROCESSING_LOCAL", "DOWNLOADING", "REMUXING"]
            is_completed = status in ["COMPLETED", "ERROR", "ABORTED"]

            if filter_idx == 1:
                should_show = is_active
            elif filter_idx == 2:
                should_show = is_completed
            else:
                should_show = True

            item.setHidden(not should_show)

        if self.dropzone_item:
            has_any_jobs = bool(self.job_widgets)
            self.dropzone_item.setHidden(has_any_jobs)

    def refresh_list(self):
        jobs = self.queue_manager.get_all_jobs()
        current_jids = {jid for jid, j in jobs.items() if j.get("mode", "Cloud (Kaggle)") == self.mode}

        # Remove deleted jobs
        for jid in list(self.job_widgets.keys()):
            if jid not in current_jids:
                item = self.job_items.pop(jid, None)
                if item:
                    row = self.list_widget.row(item)
                    self.list_widget.takeItem(row)
                widget = self.job_widgets.pop(jid, None)
                if widget:
                    widget.deleteLater()

        # Add new jobs or update existing
        sorted_jobs = sorted(
            [(jid, jobs[jid]) for jid in current_jids],
            key=lambda x: x[1].get("added_at", "")
        )

        for jid, job in sorted_jobs:
            if jid in self.job_widgets:
                self.job_widgets[jid].update_state(job)
            else:
                self.add_job_widget(jid, job)

        # Dropzone item management
        if not current_jids:
            if not self.dropzone_item:
                dropzone = DropZoneWidget()
                dropzone.clicked.connect(self._on_add_clicked)
                item = QListWidgetItem()
                item.setSizeHint(dropzone.sizeHint())
                item.setFlags(Qt.NoItemFlags)
                self.list_widget.addItem(item)
                self.list_widget.setItemWidget(item, dropzone)
                self.dropzone_item = item
                self.dropzone_widget = dropzone
            self.dropzone_item.setHidden(False)
        else:
            if self.dropzone_item:
                self.dropzone_item.setHidden(True)

        self._apply_filter()
        self.update_counts()

    def add_job_widget(self, jid: str, job: dict):
        widget = JobWidget(jid, job, mode=self.mode)
        widget.update_status(job.get("status", "PENDING"))
        widget.set_selection_mode(self.selection_mode)
        widget.apply_theme(self._theme_mode)

        widget.sig_delete_clicked.connect(self.on_delete_single)
        widget.sig_abort_clicked.connect(self.on_abort_job)
        widget.sig_open_folder_clicked.connect(self.on_open_folder_for_job)
        widget.sig_selection_toggled.connect(lambda _jid, _chk: self.update_selected_count())

        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, widget)

        self.job_widgets[jid] = widget
        self.job_items[jid] = item

    def update_counts(self):
        jobs = self.queue_manager.get_all_jobs()
        mode_jobs = [j for j in jobs.values() if j.get("mode", "Cloud (Kaggle)") == self.mode]
        active_count = sum(1 for j in mode_jobs if j.get("status") in ["PENDING", "EXTRACTING", "UPLOADING", "PROCESSING_CLOUD", "PROCESSING_LOCAL", "DOWNLOADING", "REMUXING"])
        completed_count = sum(1 for j in mode_jobs if j.get("status") in ["COMPLETED", "ERROR", "ABORTED"])
        self.switcher.set_counts(len(mode_jobs), active_count, completed_count)

    def toggle_selection_mode(self):
        self.selection_mode = not self.selection_mode
        if self.selection_mode:
            self.batch_dock.show()
            self.batch_dock.raise_()
            dock_w = min(440, self.width() - 32)
            self.batch_dock.setGeometry((self.width() - dock_w) // 2, self.height() - 56, dock_w, 42)
        else:
            self.batch_dock.hide()

        self.btn_select_mode.setText(t("btn_exit_selection") if self.selection_mode else t("btn_select_mode"))

        for widget in self.job_widgets.values():
            widget.set_selection_mode(self.selection_mode)

        self.update_selected_count()

    def update_selected_count(self):
        count = sum(1 for w in self.job_widgets.values() if w.is_selected())
        self.batch_dock.set_count(count)

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
            QMessageBox.information(self, t("alert_no_selection_title"), t("alert_no_selection_msg"))
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
            QMessageBox.information(self, t("alert_history_empty_title"), t("alert_history_empty_msg"))
            return

        dlg = DeleteConfirmDialog(len(history_jobs), self.config, self)
        if dlg.exec() == DeleteConfirmDialog.Accepted:
            self.queue_manager.clear_history(self.mode, delete_output=dlg.should_delete_files())
            self.refresh_list()

    def on_abort_job(self, job_id: str):
        self.queue_manager.abort_job(job_id)
        if job_id in self.job_widgets:
            self.job_widgets[job_id].update_status("ABORTED")
            self.job_widgets[job_id].update_message(t("msg_aborted_by_user"))
        self.update_counts()

    def on_status_updated(self, job_id: str, status: str):
        if job_id in self.job_widgets:
            self.job_widgets[job_id].update_status(status)
            self._apply_filter()
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
            display_name = t("local_engine_sub_roformer")
            size_txt = "~250 MB"
            subfolder = "RoFormer"
        elif "mdx23c" in model_name.lower():
            display_name = t("local_engine_sub_mdx23c")
            size_txt = "~150 MB"
            subfolder = "MDX23C"
        else:
            display_name = t("local_engine_sub_kim")
            size_txt = "~110 MB"
            subfolder = "Kim_Vocal_2"

        self._model_size_txt = size_txt
        self.lbl_sub.setText(display_name)

        models_dir = os.path.join(self.config.appdata_dir, "models", subfolder)
        model_path = os.path.join(models_dir, model_name)

        if os.path.exists(model_path):
            self.btn_add.setText(t("btn_add_media"))
            self._model_needs_download = False
        else:
            self.btn_add.setText(t("btn_download_model", size=size_txt))
            self._model_needs_download = True

    def _on_add_clicked(self):
        if "Local" in self.mode and getattr(self, "_model_needs_download", False):
            model_name = self._get_selected_model_name()
            subfolder = "RoFormer" if "roformer" in model_name.lower() else ("MDX23C" if "mdx23c" in model_name.lower() else "Kim_Vocal_2")
            self.download_model_clicked.emit(model_name, subfolder)
        else:
            self.add_media_clicked.emit()

    def retranslate_ui(self):
        self.lbl_engine.setText(self._get_engine_title())
        if "Cloud" in self.mode:
            self.lbl_sub.setText(self._get_engine_subtitle())
        else:
            self.update_model_button_state()

        if "Cloud" in self.mode or not getattr(self, "_model_needs_download", False):
            self.btn_add.setText(t("btn_add_media"))
        else:
            self.btn_add.setText(t("btn_download_model", size=getattr(self, "_model_size_txt", "~250 MB")))

        self.btn_select_mode.setText(t("btn_exit_selection") if self.selection_mode else t("btn_select_mode"))
        self.btn_clear_history.setText(t("btn_clear_history"))
        self.btn_mariam.setText(t("mariam_initiative"))
        self.lbl_view.setText(t("filter_label"))
        self.switcher.update_labels()
        if getattr(self, "dropzone_widget", None):
            self.dropzone_widget.retranslate_ui()
        for w in self.job_widgets.values():
            w.retranslate_ui()
        self.update_selected_count()
        self.update_counts()
