import os
import sys
import shutil
import logging
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QMessageBox, QFrame, QGridLayout,
    QGraphicsBlurEffect, QStackedWidget, QFileDialog, QDialog, QApplication
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from .theme import (
    SIDEBAR_BG, SIDEBAR_BORDER, CANVAS_BG, CARD_BORDER,
    TEXT_HEAD, TEXT_MUTED, ACCENT_EMERALD, FONT_FAMILY,
    SUPPORTED_EXTENSIONS, get_asset_path, get_sidebar_qss
)
from .components import SidebarLogo, SidebarNavButton
from .dialogs import SettingsDialog, AudioTrackSelectDialog
from .job_queue_section import JobQueueSection

try:
    from config_manager import ConfigManager
    from queue_manager import QueueManager
    from processor_thread import JobProcessor
    from local_processor import LocalJobProcessor
    from media_engine import get_duration, probe_container
    from dependency_manager import DependencyManager, FFmpegDownloader, EngineDownloader, ModelDownloader
    from logger_setup import setup_logger
except ImportError:
    from src.config_manager import ConfigManager
    from src.queue_manager import QueueManager
    from src.processor_thread import JobProcessor
    from src.local_processor import LocalJobProcessor
    from src.media_engine import get_duration, probe_container
    from src.dependency_manager import DependencyManager, FFmpegDownloader, EngineDownloader, ModelDownloader
    from src.logger_setup import setup_logger

try:
    from i18n import t, is_rtl, set_language, apply_app_direction
except ImportError:
    from src.i18n import t, is_rtl, set_language, apply_app_direction

logger = logging.getLogger(__name__)


# ─── Main Window ─────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(980, 680)

        # Set Window and Application Icon (Multi-resolution .ico/.png)
        logo_ico = get_asset_path("logo.ico")
        logo_png = get_asset_path("logo.png")
        if os.path.exists(logo_ico):
            self.setWindowIcon(QIcon(logo_ico))
        elif os.path.exists(logo_png):
            self.setWindowIcon(QIcon(logo_png))

        self.config = ConfigManager()
        self.language = self.config.get("language", "ar")
        set_language(self.language)
        apply_app_direction(QApplication.instance(), self.language)

        setup_logger(self.config)
        
        # Cleanup any orphaned temp files from previous crashed runs
        temp_dir = os.path.join(self.config.appdata_dir, "temp")
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
                
        self.queue_manager = QueueManager()

        self.init_ui()
        self.init_threads()

    def init_ui(self):
        self.setWindowTitle(t("app_title"))
        direction = Qt.RightToLeft if is_rtl(self.language) else Qt.LeftToRight
        self.setLayoutDirection(direction)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── 1. Vertical Navigation Rail (Mirrored dynamically in RTL) ──
        self.rail = QWidget()
        self.rail.setObjectName("navigationRail")
        self.rail.setFixedWidth(72)
        self.rail.setStyleSheet(get_sidebar_qss(is_rtl(self.language)))

        rail_layout = QVBoxLayout(self.rail)
        rail_layout.setContentsMargins(8, 16, 8, 16)
        rail_layout.setSpacing(14)
        rail_layout.setAlignment(Qt.AlignHCenter)

        # Native Sprout Logo without any artificial boxes/frames
        self.logo_widget = SidebarLogo()
        self.logo_widget.setToolTip(t("logo_tooltip"))
        rail_layout.addWidget(self.logo_widget, 0, Qt.AlignCenter)

        rail_layout.addSpacing(10)

        self.btn_nav_cloud = SidebarNavButton("cloud", t("nav_cloud"))
        self.btn_nav_cloud.setToolTip(t("nav_cloud_tooltip"))
        self.btn_nav_cloud.clicked.connect(lambda: self.switch_view(0))
        rail_layout.addWidget(self.btn_nav_cloud)

        self.btn_nav_local = SidebarNavButton("local", t("nav_local"))
        self.btn_nav_local.setToolTip(t("nav_local_tooltip"))
        self.btn_nav_local.clicked.connect(lambda: self.switch_view(1))
        rail_layout.addWidget(self.btn_nav_local)

        rail_layout.addStretch()

        self.btn_nav_settings = SidebarNavButton("settings", t("nav_settings"))
        self.btn_nav_settings.setToolTip(t("nav_settings_tooltip"))
        self.btn_nav_settings.clicked.connect(self.open_settings)
        rail_layout.addWidget(self.btn_nav_settings)

        # Status Dot (Pulsing Emerald Green)
        dot_box = QHBoxLayout()
        dot_box.setAlignment(Qt.AlignCenter)
        self.lbl_status_dot = QLabel("●")
        self.lbl_status_dot.setStyleSheet(f"color: {ACCENT_EMERALD}; font-size: 11px; background: transparent; border: none;")
        self.lbl_status_dot.setToolTip(t("engine_ready_tooltip"))
        dot_box.addWidget(self.lbl_status_dot)
        rail_layout.addLayout(dot_box)

        root_layout.addWidget(self.rail)

        # ── 2. Main Stacked Workspace Canvas ──
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background-color: {CANVAS_BG};")

        self.cloud_section = JobQueueSection("Cloud (Kaggle)", self.queue_manager, self.config)
        self.cloud_section.setLayoutDirection(direction)
        self.cloud_section.add_media_clicked.connect(lambda: self.add_media("Cloud (Kaggle)"))
        self.stack.addWidget(self.cloud_section)

        self.tab_local = QWidget()
        self.setup_local_tab()
        self.stack.addWidget(self.tab_local)

        root_layout.addWidget(self.stack, 1)

        self.switch_view(0)

        self.setStyleSheet(f"""
            * {{
                font-family: {FONT_FAMILY};
            }}
            QMainWindow {{
                background-color: {CANVAS_BG};
            }}
        """)
        
        self.check_ffmpeg()

    def apply_language(self, new_lang: str):
        """Live language switching with immediate root window relayout cascade."""
        self.language = new_lang
        set_language(new_lang)
        direction = Qt.RightToLeft if is_rtl(new_lang) else Qt.LeftToRight

        # Explicit cascade down hierarchy to force immediate geometry re-evaluation in Qt 6
        app = QApplication.instance()
        if app:
            app.setLayoutDirection(direction)
        self.setLayoutDirection(direction)
        if hasattr(self, 'cloud_section'):
            self.cloud_section.setLayoutDirection(direction)
        if hasattr(self, 'local_section'):
            self.local_section.setLayoutDirection(direction)

        # Re-apply dynamic rail borders
        self.rail.setStyleSheet(get_sidebar_qss(is_rtl(new_lang)))

        # Retranslate window and rail components
        self.setWindowTitle(t("app_title"))
        self.logo_widget.retranslate_ui(t("logo_tooltip"))
        self.btn_nav_cloud.retranslate_ui(t("nav_cloud"), t("nav_cloud_tooltip"))
        self.btn_nav_local.retranslate_ui(t("nav_local"), t("nav_local_tooltip"))
        self.btn_nav_settings.retranslate_ui(t("nav_settings"), t("nav_settings_tooltip"))
        self.lbl_status_dot.setToolTip(t("engine_ready_tooltip"))

        # Retranslate overlays if active
        self.retranslate_overlays()

        # Retranslate sections
        if hasattr(self, 'cloud_section'):
            self.cloud_section.retranslate_ui()
        if hasattr(self, 'local_section'):
            self.local_section.retranslate_ui()

    def retranslate_overlays(self):
        """Retranslate active downloader overlays."""
        if hasattr(self, 'lbl_ffmpeg_title') and hasattr(self, 'ffmpeg_overlay') and self.ffmpeg_overlay.isVisible():
            self.lbl_ffmpeg_title.setText(t("ffmpeg_title"))
            self.lbl_ffmpeg_sub.setText(t("ffmpeg_desc"))
            self.btn_download_ffmpeg.setText(t("ffmpeg_btn_download"))

        if hasattr(self, 'lbl_engine_title') and hasattr(self, 'engine_overlay') and self.engine_overlay.isVisible():
            self.lbl_engine_title.setText(t("engine_title"))
            self.lbl_engine_sub.setText(t("engine_desc"))
            self.btn_download_engine.setText(t("engine_btn_download"))

    def check_ffmpeg(self):
        if not DependencyManager.has_ffmpeg():
            # Create a full-screen overlay over the central widget
            self.ffmpeg_overlay = QWidget(self.centralWidget())
            self.ffmpeg_overlay.setStyleSheet("background-color: rgba(244, 248, 245, 235);")
            self.ffmpeg_overlay.resize(self.width(), self.height())
            
            overlay_layout = QVBoxLayout(self.ffmpeg_overlay)
            overlay_layout.setAlignment(Qt.AlignCenter)

            warning_box = QFrame()
            warning_box.setStyleSheet(f"""
                QFrame {{
                    background-color: #ffffff;
                    border: 1px solid {CARD_BORDER};
                    border-radius: 12px;
                }}
            """)
            warning_box.setMinimumWidth(460)
            warning_box.setMaximumWidth(540)
            wb_layout = QVBoxLayout(warning_box)
            wb_layout.setContentsMargins(28, 26, 28, 26)
            wb_layout.setSpacing(12)

            self.lbl_ffmpeg_title = QLabel(t("ffmpeg_title"))
            self.lbl_ffmpeg_title.setStyleSheet(f"font-size: 18px; font-weight: 800; color: {TEXT_HEAD}; border: none; background: transparent;")
            self.lbl_ffmpeg_title.setAlignment(Qt.AlignCenter)
            wb_layout.addWidget(self.lbl_ffmpeg_title)

            self.lbl_ffmpeg_sub = QLabel(t("ffmpeg_desc"))
            self.lbl_ffmpeg_sub.setWordWrap(True)
            self.lbl_ffmpeg_sub.setStyleSheet(f"font-size: 13px; color: {TEXT_MUTED}; border: none; background: transparent;")
            self.lbl_ffmpeg_sub.setAlignment(Qt.AlignCenter)
            wb_layout.addWidget(self.lbl_ffmpeg_sub)
            
            self.ffmpeg_progress = QProgressBar()
            self.ffmpeg_progress.setVisible(False)
            wb_layout.addWidget(self.ffmpeg_progress)
            
            self.ffmpeg_status = QLabel("")
            self.ffmpeg_status.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; border: none; background: transparent;")
            self.ffmpeg_status.setAlignment(Qt.AlignCenter)
            self.ffmpeg_status.setVisible(False)
            wb_layout.addWidget(self.ffmpeg_status)

            self.btn_download_ffmpeg = QPushButton(t("ffmpeg_btn_download"))
            self.btn_download_ffmpeg.setCursor(Qt.PointingHandCursor)
            self.btn_download_ffmpeg.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ACCENT_EMERALD};
                    color: white;
                    font-weight: bold;
                    border-radius: 6px;
                    padding: 10px;
                }}
                QPushButton:hover {{ background-color: #047857; }}
                QPushButton:disabled {{ background-color: #a7f3d0; }}
            """)
            self.btn_download_ffmpeg.clicked.connect(self.start_ffmpeg_download)
            wb_layout.addWidget(self.btn_download_ffmpeg)

            overlay_layout.addWidget(warning_box)
            self.ffmpeg_overlay.show()
            self.stack.setEnabled(False)

    def start_ffmpeg_download(self):
        self.btn_download_ffmpeg.setEnabled(False)
        self.ffmpeg_progress.setVisible(True)
        self.ffmpeg_progress.setRange(0, 100)
        self.ffmpeg_progress.setValue(0)
        self.ffmpeg_status.setVisible(True)
        
        self.ffmpeg_thread = FFmpegDownloader()
        self.ffmpeg_thread.progress_update.connect(self.ffmpeg_progress.setValue)
        self.ffmpeg_thread.status_update.connect(self.ffmpeg_status.setText)
        self.ffmpeg_thread.finished_download.connect(self.on_ffmpeg_downloaded)
        self.ffmpeg_thread.start()
        
    def on_ffmpeg_downloaded(self, success: bool, message: str):
        if success:
            self.ffmpeg_overlay.setVisible(False)
            self.stack.setEnabled(True)
            self.ffmpeg_overlay.deleteLater()
        else:
            self.btn_download_ffmpeg.setEnabled(True)
            self.ffmpeg_status.setText(t("ffmpeg_status_failed", message=message))
            self.ffmpeg_status.setStyleSheet("color: #ef4444; font-size: 11px;")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'ffmpeg_overlay') and self.ffmpeg_overlay.isVisible():
            self.ffmpeg_overlay.resize(self.width(), self.height())

    def switch_view(self, index: int):
        self.stack.setCurrentIndex(index)
        self.btn_nav_cloud.set_active(index == 0)
        self.btn_nav_local.set_active(index == 1)

    def setup_local_tab(self):
        grid = QGridLayout(self.tab_local)
        grid.setContentsMargins(0, 0, 0, 0)

        direction = Qt.RightToLeft if is_rtl(self.language) else Qt.LeftToRight
        self.local_section = JobQueueSection("Local (GPU)", self.queue_manager, self.config)
        self.local_section.setLayoutDirection(direction)
        self.local_section.add_media_clicked.connect(lambda: self.add_media("Local (GPU)"))
        self.local_section.download_model_clicked.connect(self.download_local_model)
        grid.addWidget(self.local_section, 0, 0)

        if not DependencyManager.has_local_engine():
            blur = QGraphicsBlurEffect()
            blur.setBlurRadius(10)
            self.local_section.setGraphicsEffect(blur)
            self.local_section.setEnabled(False)

            self.engine_overlay = QWidget()
            self.engine_overlay.setStyleSheet("background-color: rgba(244, 248, 245, 215);")
            overlay_layout = QVBoxLayout(self.engine_overlay)
            overlay_layout.setAlignment(Qt.AlignCenter)

            warning_box = QFrame()
            warning_box.setStyleSheet(f"""
                QFrame {{
                    background-color: #ffffff;
                    border: 1px solid {CARD_BORDER};
                    border-radius: 12px;
                }}
            """)
            warning_box.setMinimumWidth(460)
            warning_box.setMaximumWidth(540)
            wb_layout = QVBoxLayout(warning_box)
            wb_layout.setContentsMargins(28, 26, 28, 26)
            wb_layout.setSpacing(12)

            self.lbl_engine_title = QLabel(t("engine_title"))
            self.lbl_engine_title.setStyleSheet(f"font-size: 18px; font-weight: 800; color: {TEXT_HEAD}; border: none; background: transparent;")
            self.lbl_engine_title.setAlignment(Qt.AlignCenter)
            wb_layout.addWidget(self.lbl_engine_title)

            self.lbl_engine_sub = QLabel(t("engine_desc"))
            self.lbl_engine_sub.setWordWrap(True)
            self.lbl_engine_sub.setStyleSheet(f"font-size: 13px; color: {TEXT_MUTED}; border: none; background: transparent;")
            self.lbl_engine_sub.setAlignment(Qt.AlignCenter)
            wb_layout.addWidget(self.lbl_engine_sub)
            
            self.engine_progress = QProgressBar()
            self.engine_progress.setVisible(False)
            wb_layout.addWidget(self.engine_progress)
            
            self.engine_status = QLabel("")
            self.engine_status.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; border: none; background: transparent;")
            self.engine_status.setAlignment(Qt.AlignCenter)
            self.engine_status.setVisible(False)
            wb_layout.addWidget(self.engine_status)

            self.btn_download_engine = QPushButton(t("engine_btn_download"))
            self.btn_download_engine.setCursor(Qt.PointingHandCursor)
            self.btn_download_engine.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ACCENT_EMERALD};
                    color: white;
                    font-weight: bold;
                    border-radius: 6px;
                    padding: 10px;
                }}
                QPushButton:hover {{ background-color: #047857; }}
                QPushButton:disabled {{ background-color: #a7f3d0; }}
            """)
            self.btn_download_engine.clicked.connect(self.start_engine_download)
            wb_layout.addWidget(self.btn_download_engine)

            overlay_layout.addWidget(warning_box)
            grid.addWidget(self.engine_overlay, 0, 0)

    def start_engine_download(self):
        self.btn_download_engine.setEnabled(False)
        self.engine_progress.setVisible(True)
        self.engine_progress.setRange(0, 100)
        self.engine_progress.setValue(0)
        self.engine_status.setVisible(True)
        
        self.engine_thread = EngineDownloader()
        self.engine_thread.progress_update.connect(self.engine_progress.setValue)
        self.engine_thread.status_update.connect(self.engine_status.setText)
        self.engine_thread.finished_download.connect(self.on_engine_downloaded)
        self.engine_thread.start()
        
    def on_engine_downloaded(self, success: bool, message: str):
        if success:
            self.engine_overlay.setVisible(False)
            self.local_section.setGraphicsEffect(None)
            self.local_section.setEnabled(True)
        else:
            self.btn_download_engine.setEnabled(True)
            self.engine_status.setText(t("engine_status_failed", message=message))
            self.engine_status.setStyleSheet("color: #ef4444; font-size: 11px;")

    def download_local_model(self, model_name: str, subfolder: str):
        self.local_section.btn_add.setEnabled(False)
        self.local_section.btn_add.setText(t("btn_downloading_model"))
        
        models_dir = os.path.join(self.config.appdata_dir, "models", subfolder)
        os.makedirs(models_dir, exist_ok=True)
        
        self.model_thread = ModelDownloader(model_name, models_dir)
        self.model_thread.status_update.connect(lambda text: self.local_section.btn_add.setText(text))
        self.model_thread.finished_download.connect(self.on_model_downloaded)
        self.model_thread.start()
        
    def on_model_downloaded(self, success: bool, message: str):
        if success:
            self.local_section.update_model_button_state()
            self.local_section.btn_add.setEnabled(True)
        else:
            QMessageBox.critical(self, t("alert_download_failed_title"), t("alert_download_failed_msg", message=message))
            self.local_section.btn_add.setEnabled(True)
            self.local_section.update_model_button_state()

    def open_settings(self):
        old_lang = self.language
        old_user = self.config.get("kaggle_username")
        old_key = self.config.get("kaggle_api_key")
        old_logging = self.config.get("enable_logging")

        dlg = SettingsDialog(self.config, self)
        if dlg.exec() == QDialog.Accepted:
            dlg.save_and_get_config()
            new_lang = self.config.get("language", "ar")
            new_user = self.config.get("kaggle_username")
            new_key = self.config.get("kaggle_api_key")
            new_logging = self.config.get("enable_logging")

            if new_lang != old_lang:
                self.apply_language(new_lang)

            if new_logging != old_logging:
                setup_logger(self.config)

            # Only re-initialize background threads if Kaggle credentials actually changed!
            if new_user != old_user or new_key != old_key:
                self.init_threads()

            QMessageBox.information(self, t("alert_saved_title"), t("alert_saved_msg"))
            if hasattr(self, 'local_section'):
                self.local_section.update_model_button_state()

    def init_threads(self):
        username = self.config.get("kaggle_username")
        api_key = self.config.get("kaggle_api_key")

        if username and api_key:
            if not hasattr(self, 'cloud_thread') or not self.cloud_thread.isRunning():
                self.cloud_thread = JobProcessor(self.queue_manager, username, api_key)
                self.cloud_thread.progress_update.connect(self.cloud_section.on_progress_updated)
                self.cloud_thread.status_update.connect(self.cloud_section.on_status_updated)
                self.cloud_thread.error_job.connect(self.on_job_error)
                self.cloud_thread.start()
            else:
                self.cloud_thread.update_credentials(username, api_key)

        # Initialize Local Thread
        if not hasattr(self, 'local_thread') or not self.local_thread.isRunning():
            self.local_thread = LocalJobProcessor(self.queue_manager, self.config)
            self.local_thread.progress_update.connect(self.local_section.on_progress_updated)
            self.local_thread.status_update.connect(self.local_section.on_status_updated)
            self.local_thread.error_job.connect(self.on_job_error)
            self.local_thread.start()

    def add_video(self, mode: str):
        self.add_media(mode)

    def add_media(self, mode: str):
        if mode == "Cloud (Kaggle)":
            self.init_threads()
            if not self.config.get("kaggle_username"):
                QMessageBox.warning(self, t("alert_missing_creds_title"), t("alert_missing_creds_msg"))
                self.open_settings()
                return

        # Pre-flight check: Verify and create output directory upfront
        try:
            out_dir = self.config.get_output_folder(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            if not os.path.exists(out_dir):
                os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, t("alert_perm_denied_title"), t("alert_perm_denied_msg", error=str(e)))
            return

        file_filter = (
            f"{t('filter_supported_media')} (*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.weba *.m4a *.m4b *.mka *.mp3 *.wav *.flac *.aac *.ogg *.opus);;"
            f"{t('filter_video_files')} (*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm);;"
            f"{t('filter_audio_files')} (*.mp3 *.wav *.flac *.m4a *.m4b *.mka *.weba *.aac *.ogg *.opus);;"
            f"{t('filter_all_files')} (*.*)"
        )
        files, _ = QFileDialog.getOpenFileNames(self, t("file_dialog_title"), "", file_filter)
        if not files:
            return

        # Pre-Flight Validation Guard
        valid_files = []
        invalid_files = []
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                valid_files.append(f)
            else:
                invalid_files.append(os.path.basename(f))

        if invalid_files:
            supported_list = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            QMessageBox.warning(
                self,
                t("alert_unsupported_title"),
                t("alert_unsupported_msg", files="\n".join(invalid_files), supported=supported_list)
            )

        if not valid_files:
            return

        model_selection = self.config.get("local_model", "")
        if "RoFormer" in model_selection:
            display_model = "RoFormer"
        elif "MDX23C" in model_selection:
            display_model = "MDX23C"
        else:
            display_model = "Kim Vocal 2"

        for file in valid_files:
            # Audio Stream Inspection
            try:
                probe_result = probe_container(file)
            except Exception as e:
                QMessageBox.warning(
                    self,
                    t("alert_analysis_err_title"),
                    t("alert_analysis_err_msg", filename=os.path.basename(file), error=str(e))
                )
                continue

            audio_streams = probe_result.get("audio_streams", [])

            # Zero-Audio Guard: Empty Container Trap
            if len(audio_streams) == 0:
                QMessageBox.warning(
                    self,
                    t("alert_no_audio_title"),
                    t("alert_no_audio_msg", filename=os.path.basename(file))
                )
                continue

            # Stream selection logic
            chosen_index = 0
            if len(audio_streams) > 1:
                dlg = AudioTrackSelectDialog(audio_streams, os.path.basename(file), self)
                if dlg.exec() != QDialog.Accepted:
                    continue
                chosen_index = dlg.get_chosen_index()

            duration = 0.0
            self.queue_manager.add_job(
                file,
                mode=mode,
                duration=duration,
                model=display_model,
                selected_audio_stream=chosen_index,
                probe_result=probe_result
            )

        if mode == "Cloud (Kaggle)":
            self.cloud_section.refresh_list()
        else:
            self.local_section.refresh_list()

    def on_job_error(self, jid: str, error_msg: str):
        QMessageBox.critical(self, t("alert_job_err_title"), t("alert_job_err_msg", error=error_msg))

    def closeEvent(self, event):
        if hasattr(self, 'cloud_thread') and self.cloud_thread is not None:
            self.cloud_thread.stop()
        if hasattr(self, 'local_thread') and self.local_thread is not None:
            self.local_thread.stop()

        for t_name in ['cloud_thread', 'local_thread']:
            thread = getattr(self, t_name, None)
            if thread and thread.isRunning():
                if not thread.wait(2000):
                    logger.warning(f"{t_name} did not exit within timeout; terminating.")
                    try:
                        thread.terminate()
                        thread.wait(500)
                    except Exception:
                        pass
        event.accept()
