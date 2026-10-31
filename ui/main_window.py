import os
import sys
import shutil
import logging
import traceback
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QMessageBox, QFrame, QGridLayout,
    QGraphicsBlurEffect, QStackedWidget, QFileDialog, QDialog, QApplication
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QFont

from .theme import (
    Theme, ThemeMode, FONT_FAMILY, get_font_family,
    SUPPORTED_EXTENSIONS, get_asset_path, get_sidebar_qss
)
from .components import (
    SidebarLogo, SidebarNavButton, SidebarThemeButton, EngineTelemetryPill
)
from .dialogs import SettingsDialog, AudioTrackSelectDialog
from .job_queue_section import JobQueueSection
from .overlay_widgets import DownloadOverlayWidget
from .update_banner import UpdateBannerWidget

try:
    from update_checker import GitHubUpdateChecker
    from config_manager import ConfigManager
    from queue_manager import QueueManager
    from processor_thread import JobProcessor
    from local_processor import LocalJobProcessor
    from media_engine import probe_container
    from dependency_manager import DependencyManager, FFmpegDownloader, EngineDownloader, ModelDownloader
    from logger_setup import setup_logger
    from i18n import t, is_rtl, set_language, apply_app_direction
except ImportError:
    from src.update_checker import GitHubUpdateChecker
    from src.config_manager import ConfigManager
    from src.queue_manager import QueueManager
    from src.processor_thread import JobProcessor
    from src.local_processor import LocalJobProcessor
    from src.media_engine import probe_container
    from src.dependency_manager import DependencyManager, FFmpegDownloader, EngineDownloader, ModelDownloader
    from src.logger_setup import setup_logger
    from src.i18n import t, is_rtl, set_language, apply_app_direction

logger = logging.getLogger(__name__)


def set_native_window_theme(window: QWidget, dark: bool):
    """Integrates Windows native DWM immersive dark title bar."""
    if sys.platform != "win32":
        return
    try:
        if not window.isVisible():
            return
        import ctypes
        hwnd = int(window.winId())
        val = ctypes.c_int(1 if dark else 0)
        if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), ctypes.sizeof(val)) != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(val), ctypes.sizeof(val))
    except Exception as e:
        logger.debug(f"Could not set native window theme: {e}")


# ─── Main Application Window ──────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(980, 680)

        # Set Multi-resolution Application Icon
        logo_ico = get_asset_path("logo.ico")
        logo_png = get_asset_path("logo.png")
        if os.path.exists(logo_ico):
            self.setWindowIcon(QIcon(logo_ico))
        elif os.path.exists(logo_png):
            self.setWindowIcon(QIcon(logo_png))

        self.config = ConfigManager()

        # Language setup (Arabic default)
        self.language = self.config.get("language", "ar")
        set_language(self.language)
        apply_app_direction(QApplication.instance(), self.language)

        # Theme setup (Light mode DEFAULT)
        self.theme_mode = self.config.get("theme_mode", ThemeMode.LIGHT)
        Theme.set_mode(self.theme_mode)

        setup_logger(self.config)

        # Cleanup orphaned temp files
        temp_dir = os.path.join(self.config.appdata_dir, "temp")
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

        self.queue_manager = QueueManager()
        self.update_checker = None

        self.init_ui()
        self.init_threads()

        # Non-blocking auto-update check delayed 2.5s for instant startup
        self._auto_update_timer = QTimer(self)
        self._auto_update_timer.setSingleShot(True)
        self._auto_update_timer.timeout.connect(self.start_auto_update_check)
        self._auto_update_timer.start(2500)

    def init_ui(self):
        self.setWindowTitle(t("app_title"))
        direction = Qt.RightToLeft if is_rtl(self.language) else Qt.LeftToRight
        self.setLayoutDirection(direction)

        self.central_widget = QWidget()
        self.central_widget.setObjectName("centralCanvas")
        self.central_widget.setAttribute(Qt.WA_StyledBackground, True)
        self.setCentralWidget(self.central_widget)

        root_layout = QHBoxLayout(self.central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── 1. Vertical Navigation Studio Rail ──
        self.rail = QWidget()
        self.rail.setObjectName("navigationRail")
        self.rail.setFixedWidth(72)
        self.rail.setStyleSheet(get_sidebar_qss(is_rtl(self.language), self.theme_mode))

        rail_layout = QVBoxLayout(self.rail)
        rail_layout.setContentsMargins(6, 14, 6, 14)
        rail_layout.setSpacing(10)
        rail_layout.setAlignment(Qt.AlignHCenter)

        # Native Sprout Logo with version pill ("v2.0")
        self.logo_widget = SidebarLogo()
        rail_layout.addWidget(self.logo_widget, 0, Qt.AlignCenter)
        rail_layout.addSpacing(6)

        # Cloud Navigation Button
        self.btn_nav_cloud = SidebarNavButton("cloud", t("nav_cloud"))
        self.btn_nav_cloud.setToolTip(t("nav_cloud_tooltip"))
        self.btn_nav_cloud.clicked.connect(lambda: self.switch_view(0))
        rail_layout.addWidget(self.btn_nav_cloud)

        # Local Navigation Button
        self.btn_nav_local = SidebarNavButton("local", t("nav_local"))
        self.btn_nav_local.setToolTip(t("nav_local_tooltip"))
        self.btn_nav_local.clicked.connect(lambda: self.switch_view(1))
        rail_layout.addWidget(self.btn_nav_local)

        rail_layout.addStretch()

        # Direct Theme Toggle Button in the Rail (☀ Sun / 🌙 Moon)
        self.btn_theme = SidebarThemeButton(self.theme_mode)
        self.btn_theme.clicked.connect(self.toggle_theme)
        rail_layout.addWidget(self.btn_theme, 0, Qt.AlignCenter)

        # Settings Navigation Button
        self.btn_nav_settings = SidebarNavButton("settings", t("nav_settings"))
        self.btn_nav_settings.setToolTip(t("nav_settings_tooltip"))
        self.btn_nav_settings.clicked.connect(self.open_settings)
        rail_layout.addWidget(self.btn_nav_settings)

        # Serene Engine Telemetry Pill (Static solid dot when idle; 3s breath when busy)
        self.telemetry_pill = EngineTelemetryPill()
        rail_layout.addWidget(self.telemetry_pill, 0, Qt.AlignCenter)

        root_layout.addWidget(self.rail)

        # ── 2. Main Stacked Workspace Canvas ──
        self.workspace_container = QWidget()
        self.workspace_container.setStyleSheet("background: transparent; border: none;")
        workspace_layout = QVBoxLayout(self.workspace_container)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)

        self.update_banner = UpdateBannerWidget(self.config, self)
        self.update_banner.setVisible(False)
        workspace_layout.addWidget(self.update_banner)

        self.stack = QStackedWidget()

        self.cloud_section = JobQueueSection("Cloud (Kaggle)", self.queue_manager, self.config)
        self.cloud_section.setLayoutDirection(direction)
        self.cloud_section.add_media_clicked.connect(lambda: self.add_media("Cloud (Kaggle)"))
        self.stack.addWidget(self.cloud_section)

        self.tab_local = QWidget()
        self.setup_local_tab()
        self.stack.addWidget(self.tab_local)

        workspace_layout.addWidget(self.stack, 1)
        root_layout.addWidget(self.workspace_container, 1)

        self.apply_theme(self.theme_mode)
        self.switch_view(0)
        self.check_ffmpeg()

    def toggle_theme(self):
        new_mode = ThemeMode.DARK if self.theme_mode == ThemeMode.LIGHT else ThemeMode.LIGHT
        self.theme_mode = new_mode
        Theme.set_mode(new_mode)
        self.config.set("theme_mode", new_mode)
        self.btn_theme.set_theme_mode(new_mode)
        self.apply_theme(new_mode)

    def apply_theme(self, mode: str):
        self.theme_mode = mode
        Theme.set_mode(mode)
        canvas_bg = Theme.get_token("CANVAS_BG", mode)

        self.rail.setStyleSheet(get_sidebar_qss(is_rtl(self.language), mode))
        self.stack.setStyleSheet(f"background-color: {canvas_bg};")
        if hasattr(self, 'central_widget'):
            self.central_widget.setStyleSheet(f"QWidget#centralCanvas {{ background-color: {canvas_bg}; }}")
        active_font = get_font_family(self.language)
        app = QApplication.instance()
        if app:
            qf = QFont(active_font)
            qf.setStyleStrategy(QFont.PreferAntialias | QFont.PreferQuality)
            app.setFont(qf)

        self.setStyleSheet(f'* {{ font-family: "{active_font}"; }} QMainWindow {{ background-color: {canvas_bg}; }}')

        if hasattr(self, 'cloud_section'):
            self.cloud_section.apply_theme(mode)
        if hasattr(self, 'local_section'):
            self.local_section.apply_theme(mode)
        if hasattr(self, 'update_banner'):
            self.update_banner.apply_theme(mode)
        set_native_window_theme(self, mode == ThemeMode.DARK)

    def showEvent(self, event):
        super().showEvent(event)
        set_native_window_theme(self, self.theme_mode == ThemeMode.DARK)

    def apply_language(self, new_lang: str):
        """Live language switching with immediate root window relayout cascade."""
        self.language = new_lang
        set_language(new_lang)
        direction = Qt.RightToLeft if is_rtl(new_lang) else Qt.LeftToRight

        app = QApplication.instance()
        if app:
            app.setLayoutDirection(direction)
        self.setLayoutDirection(direction)
        if hasattr(self, 'cloud_section'):
            self.cloud_section.setLayoutDirection(direction)
        if hasattr(self, 'local_section'):
            self.local_section.setLayoutDirection(direction)

        active_font = get_font_family(new_lang)
        if app:
            qf = QFont(active_font)
            qf.setStyleStrategy(QFont.PreferAntialias | QFont.PreferQuality)
            app.setFont(qf)

        canvas_bg = Theme.get_token("CANVAS_BG", self.theme_mode)
        self.setStyleSheet(f'* {{ font-family: "{active_font}"; }} QMainWindow {{ background-color: {canvas_bg}; }}')
        self.rail.setStyleSheet(get_sidebar_qss(is_rtl(new_lang), self.theme_mode))
        self.setWindowTitle(t("app_title"))
        self.logo_widget.retranslate_ui(t("logo_tooltip"))
        self.btn_nav_cloud.retranslate_ui(t("nav_cloud"), t("nav_cloud_tooltip"))
        self.btn_nav_local.retranslate_ui(t("nav_local"), t("nav_local_tooltip"))
        self.btn_nav_settings.retranslate_ui(t("nav_settings"), t("nav_settings_tooltip"))
        self.btn_theme._update_tooltip()
        self.telemetry_pill.retranslate_ui()

        if hasattr(self, 'cloud_section'):
            self.cloud_section.retranslate_ui()
        if hasattr(self, 'local_section'):
            self.local_section.retranslate_ui()
        if hasattr(self, 'update_banner'):
            self.update_banner.retranslate_ui(new_lang)

    def check_ffmpeg(self):
        if not DependencyManager.has_ffmpeg():
            self.ffmpeg_overlay = DownloadOverlayWidget(
                t("ffmpeg_title"), t("ffmpeg_desc"), t("ffmpeg_btn_download"), self.centralWidget()
            )
            self.ffmpeg_overlay.resize(self.width(), self.height())
            self.ffmpeg_overlay.btn_download.clicked.connect(self.start_ffmpeg_download)
            self.ffmpeg_overlay.show()
            self.stack.setEnabled(False)

    def start_ffmpeg_download(self):
        self.ffmpeg_overlay.set_downloading()
        self.ffmpeg_thread = FFmpegDownloader()
        self.ffmpeg_thread.progress_update.connect(self.ffmpeg_overlay.progress.setValue)
        self.ffmpeg_thread.status_update.connect(self.ffmpeg_overlay.lbl_status.setText)
        self.ffmpeg_thread.finished_download.connect(self.on_ffmpeg_downloaded)
        self.ffmpeg_thread.start()

    def on_ffmpeg_downloaded(self, success: bool, message: str):
        if success:
            self.ffmpeg_overlay.setVisible(False)
            self.stack.setEnabled(True)
            self.ffmpeg_overlay.deleteLater()
        else:
            self.ffmpeg_overlay.set_error(t("ffmpeg_status_failed", message=message))

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

            self.engine_overlay = DownloadOverlayWidget(
                t("engine_title"), t("engine_desc"), t("engine_btn_download")
            )
            self.engine_overlay.btn_download.clicked.connect(self.start_engine_download)
            grid.addWidget(self.engine_overlay, 0, 0)

    def start_engine_download(self):
        self.engine_overlay.set_downloading()
        self.engine_thread = EngineDownloader()
        self.engine_thread.progress_update.connect(self.engine_overlay.progress.setValue)
        self.engine_thread.status_update.connect(self.engine_overlay.lbl_status.setText)
        self.engine_thread.finished_download.connect(self.on_engine_downloaded)
        self.engine_thread.start()

    def on_engine_downloaded(self, success: bool, message: str):
        if success:
            self.engine_overlay.setVisible(False)
            self.local_section.setGraphicsEffect(None)
            self.local_section.setEnabled(True)
        else:
            self.engine_overlay.set_error(t("engine_status_failed", message=message))

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
        self.local_section.btn_add.setEnabled(True)
        self.local_section.update_model_button_state()
        if not success:
            QMessageBox.critical(self, t("alert_download_failed_title"), t("alert_download_failed_msg", message=message))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'ffmpeg_overlay') and self.ffmpeg_overlay.isVisible():
            self.ffmpeg_overlay.resize(self.width(), self.height())

    def switch_view(self, index: int):
        self.stack.setCurrentIndex(index)
        self.btn_nav_cloud.set_active(index == 0)
        self.btn_nav_local.set_active(index == 1)

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
                self.cloud_thread.status_update.connect(self.on_thread_status_update)
                self.cloud_thread.error_job.connect(self.on_job_error)
                self.cloud_thread.start()
            else:
                self.cloud_thread.update_credentials(username, api_key)

        if not hasattr(self, 'local_thread') or not self.local_thread.isRunning():
            self.local_thread = LocalJobProcessor(self.queue_manager, self.config)
            self.local_thread.progress_update.connect(self.local_section.on_progress_updated)
            self.local_thread.status_update.connect(self.on_thread_status_update)
            self.local_thread.error_job.connect(self.on_job_error)
            self.local_thread.start()

    def on_thread_status_update(self, job_id: str, status: str):
        if hasattr(self, 'cloud_section'):
            self.cloud_section.on_status_updated(job_id, status)
        if hasattr(self, 'local_section'):
            self.local_section.on_status_updated(job_id, status)
        # Check if any active job is processing
        has_active = any(
            j.get("status") in ["EXTRACTING", "UPLOADING", "PROCESSING_CLOUD", "PROCESSING_LOCAL", "DOWNLOADING", "REMUXING"]
            for j in self.queue_manager.get_all_jobs().values()
        )
        self.telemetry_pill.set_active_processing(has_active)

    def add_video(self, mode: str):
        self.add_media(mode)

    def add_media(self, mode: str):
        if getattr(self, "_is_adding_media", False):
            return
        self._is_adding_media = True
        try:
            if mode == "Cloud (Kaggle)":
                username = (self.config.get("kaggle_username") or "").strip()
                api_key = (self.config.get("kaggle_api_key") or "").strip()
                if not username or not api_key:
                    QMessageBox.warning(self, t("alert_missing_creds_title"), t("alert_missing_creds_msg"))
                    self.open_settings()
                    username = (self.config.get("kaggle_username") or "").strip()
                    api_key = (self.config.get("kaggle_api_key") or "").strip()
                    if not username or not api_key:
                        return

                if not hasattr(self, 'cloud_thread') or not self.cloud_thread.isRunning():
                    self.init_threads()

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

            files = list(dict.fromkeys(files))
            valid_files = [f for f in files if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS]
            invalid_files = [os.path.basename(f) for f in files if os.path.splitext(f)[1].lower() not in SUPPORTED_EXTENSIONS]

            if invalid_files:
                supported_list = ", ".join(sorted(SUPPORTED_EXTENSIONS))
                QMessageBox.warning(
                    self, t("alert_unsupported_title"),
                    t("alert_unsupported_msg", files="\n".join(invalid_files), supported=supported_list)
                )

            if not valid_files:
                return

            model_selection = self.config.get("local_model", "")
            display_model = "RoFormer" if "RoFormer" in model_selection else ("MDX23C" if "MDX23C" in model_selection else "Kim Vocal 2")

            probed_files = []
            multi_track_files = {}

            for file in valid_files:
                try:
                    probe_result = probe_container(file)
                except Exception as e:
                    QMessageBox.warning(self, t("alert_analysis_err_title"), t("alert_analysis_err_msg", filename=os.path.basename(file), error=str(e)))
                    continue

                audio_streams = probe_result.get("audio_streams", [])
                if len(audio_streams) == 0:
                    QMessageBox.warning(self, t("alert_no_audio_title"), t("alert_no_audio_msg", filename=os.path.basename(file)))
                    continue

                try:
                    media_dur = float(probe_result.get("format", {}).get("duration", 0.0))
                except (TypeError, ValueError):
                    media_dur = 0.0

                if len(audio_streams) > 1:
                    multi_track_files[file] = audio_streams

                probed_files.append((file, probe_result, media_dur))

            if not probed_files:
                return

            chosen_tracks = {}
            if multi_track_files:
                dlg = AudioTrackSelectDialog(multi_track_files, self)
                if dlg.exec() != QDialog.Accepted:
                    return
                chosen_tracks = dlg.get_selected_tracks()

            for file, probe_result, media_dur in probed_files:
                chosen_index = chosen_tracks.get(file, 0)
                self.queue_manager.add_job(
                    file, mode=mode, duration=media_dur, model=display_model,
                    selected_audio_stream=chosen_index, probe_result=probe_result,
                    save=False
                )

            self.queue_manager._save_state()

            if mode == "Cloud (Kaggle)":
                self.cloud_section.refresh_list()
            else:
                self.local_section.refresh_list()
        finally:
            self._is_adding_media = False

    def on_job_error(self, jid: str, error_msg: str):
        QMessageBox.critical(self, t("alert_job_err_title"), t("alert_job_err_msg", error=error_msg))

    def start_auto_update_check(self):
        """Spawns non-blocking GitHub release check in background thread."""
        if not self.config.get("check_updates", True):
            return
        self.update_checker = GitHubUpdateChecker(config=self.config, force=False, parent=None)
        self.update_checker.sig_update_available.connect(self.on_update_available)
        self.update_checker.start()

    def on_update_available(self, latest_version: str, release_notes: str, html_url: str, download_url: str):
        """Displays update banner when newer version is detected."""
        self.update_banner.show_update(latest_version, release_notes, html_url, download_url)

    def closeEvent(self, event):
        has_active = any(
            j.get("status") in ["EXTRACTING", "UPLOADING", "PROCESSING_CLOUD", "PROCESSING_LOCAL", "DOWNLOADING", "REMUXING"]
            for j in self.queue_manager.get_all_jobs().values()
        )
        if has_active:
            from .overlay_widgets import CloseActiveJobDialog
            dlg = CloseActiveJobDialog(self)
            if dlg.exec() != QDialog.Accepted:
                event.ignore()
                return

        for jid, j in self.queue_manager.get_all_jobs().items():
            if j.get("status") in ["EXTRACTING", "UPLOADING", "PROCESSING_CLOUD", "PROCESSING_LOCAL", "DOWNLOADING", "REMUXING"]:
                self.queue_manager.abort_job(jid)

        if hasattr(self, '_auto_update_timer') and self._auto_update_timer.isActive():
            self._auto_update_timer.stop()
        try:
            from update_checker import stop_all_active_checkers
            stop_all_active_checkers()
        except Exception:
            pass

        try:
            from process_tracker import cleanup_all_subprocesses, terminate_qt_threads
            threads = [
                getattr(self, n, None) for n in
                ['cloud_thread', 'local_thread', 'ffmpeg_thread', 'engine_thread', 'model_thread', 'update_checker']
            ]
            terminate_qt_threads([t for t in threads if t is not None], timeout_ms=500)
            cleanup_all_subprocesses()
        except Exception:
            pass

        event.accept()
