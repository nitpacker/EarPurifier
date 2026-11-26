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
from .dialogs import SettingsDialog, AudioTrackSelectDialog, PhoneVerificationWarningDialog
from .job_queue_section import JobQueueSection
from .overlay_widgets import DownloadOverlayWidget, VerificationReminderBanner, GpuUpgradeBanner
from .update_banner import UpdateBannerWidget

try:
    from update_checker import GitHubUpdateChecker
    from config_manager import ConfigManager
    from queue_manager import QueueManager
    from processor_thread import JobProcessor
    from local_processor import LocalJobProcessor
    from media_engine import probe_container
    from dependency_manager import (
        DependencyManager, FFmpegDownloader, EngineDownloader, ModelDownloader,
        classify_local_error, is_ffmpeg_missing_error,
    )
    from logger_setup import setup_logger
    from i18n import t, is_rtl, set_language, apply_app_direction
except ImportError:
    from src.update_checker import GitHubUpdateChecker
    from src.config_manager import ConfigManager
    from src.queue_manager import QueueManager
    from src.processor_thread import JobProcessor
    from src.local_processor import LocalJobProcessor
    from src.media_engine import probe_container
    from src.dependency_manager import (
        DependencyManager, FFmpegDownloader, EngineDownloader, ModelDownloader,
        classify_local_error, is_ffmpeg_missing_error,
    )
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
        if sys.platform == "win32":
            icon_path = logo_ico if os.path.exists(logo_ico) else logo_png
        else:
            icon_path = logo_png if os.path.exists(logo_png) else logo_ico
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

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
        self.ffmpeg_overlay = None
        self.engine_overlay = None
        self.gpu_upgrade_banner = None
        self.ffmpeg_thread = None
        self.engine_thread = None
        self.model_thread = None
        self._retired_model_threads = []

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

        self.verification_banner = VerificationReminderBanner(self)
        self.verification_banner.setVisible(False)
        workspace_layout.addWidget(self.verification_banner)

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
        if hasattr(self, 'verification_banner') and self.verification_banner is not None:
            self.verification_banner.apply_theme(mode)
        if getattr(self, 'gpu_upgrade_banner', None) is not None:
            self.gpu_upgrade_banner.apply_theme(mode)
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
        if hasattr(self, 'verification_banner') and self.verification_banner is not None:
            self.verification_banner.retranslate_ui(new_lang)
        if getattr(self, 'gpu_upgrade_banner', None) is not None:
            self.gpu_upgrade_banner.retranslate_ui(new_lang)
        if getattr(self, 'ffmpeg_overlay', None) is not None:
            try:
                if self.ffmpeg_overlay.isVisible():
                    self.ffmpeg_overlay.lbl_title.setText(t("ffmpeg_title"))
                    self.ffmpeg_overlay.lbl_desc.setText(t("ffmpeg_desc"))
                    self.ffmpeg_overlay.btn_download.setText(t("ffmpeg_btn_download"))
                    if getattr(self.ffmpeg_overlay, "_raw_status", None):
                        self.ffmpeg_overlay.set_status_message(self.ffmpeg_overlay._raw_status)
            except RuntimeError:
                self.ffmpeg_overlay = None
        if getattr(self, 'engine_overlay', None) is not None:
            try:
                if self.engine_overlay.isVisible():
                    engine_size = "~2.7 GB" if DependencyManager.has_nvidia_gpu() else "~350 MB"
                    self.engine_overlay.lbl_title.setText(t("engine_title"))
                    self.engine_overlay.lbl_desc.setText(t("engine_desc", size=engine_size))
                    self.engine_overlay.btn_download.setText(t("engine_btn_download"))
                    if getattr(self.engine_overlay, "_raw_status", None):
                        self.engine_overlay.set_status_message(self.engine_overlay._raw_status)
            except RuntimeError:
                self.engine_overlay = None

    def check_ffmpeg(self):
        if not DependencyManager.has_ffmpeg():
            existing = getattr(self, 'ffmpeg_overlay', None)
            if existing is not None:
                try:
                    if existing.isVisible():
                        existing.raise_()
                        return
                except RuntimeError:
                    self.ffmpeg_overlay = None

            cw = self.centralWidget()
            self.ffmpeg_overlay = DownloadOverlayWidget(
                t("ffmpeg_title"), t("ffmpeg_desc"), t("ffmpeg_btn_download"), cw
            )
            if cw is not None:
                self.ffmpeg_overlay.resize(cw.size())
            else:
                self.ffmpeg_overlay.resize(self.width(), self.height())
            self.ffmpeg_overlay.btn_download.clicked.connect(self.start_ffmpeg_download)
            self.ffmpeg_overlay.show()
            self.ffmpeg_overlay.raise_()
            self.stack.setEnabled(False)
            if hasattr(self, 'rail'):
                self.rail.setEnabled(False)

    def start_ffmpeg_download(self):
        if getattr(self, 'ffmpeg_overlay', None) is None:
            return
        if getattr(self, 'ffmpeg_thread', None) is not None and self.ffmpeg_thread.isRunning():
            return
        self.ffmpeg_overlay.set_downloading()
        self.ffmpeg_thread = FFmpegDownloader()
        self.ffmpeg_thread.progress_update.connect(self.ffmpeg_overlay.set_progress)
        self.ffmpeg_thread.status_update.connect(self.ffmpeg_overlay.set_status_message)
        self.ffmpeg_thread.finished_download.connect(self.on_ffmpeg_downloaded)
        self.ffmpeg_thread.start()

    def on_ffmpeg_downloaded(self, success: bool, message: str):
        overlay = getattr(self, 'ffmpeg_overlay', None)
        if success:
            self.ffmpeg_overlay = None
            if overlay is not None:
                try:
                    overlay.setVisible(False)
                    overlay.deleteLater()
                except RuntimeError:
                    pass
            self.stack.setEnabled(True)
            if hasattr(self, 'rail'):
                self.rail.setEnabled(True)
        else:
            if overlay is not None:
                try:
                    overlay.set_error(t("ffmpeg_status_failed", message=message))
                except RuntimeError:
                    self.ffmpeg_overlay = None

    def setup_local_tab(self):
        grid = QGridLayout(self.tab_local)
        grid.setContentsMargins(0, 0, 0, 0)

        direction = Qt.RightToLeft if is_rtl(self.language) else Qt.LeftToRight
        local_container = QWidget(self.tab_local)
        local_container.setStyleSheet("background: transparent; border: none;")
        local_layout = QVBoxLayout(local_container)
        local_layout.setContentsMargins(0, 0, 0, 0)
        local_layout.setSpacing(0)

        self.gpu_upgrade_banner = GpuUpgradeBanner(local_container)
        self.gpu_upgrade_banner.upgrade_requested.connect(self.start_gpu_engine_upgrade)
        local_layout.addWidget(self.gpu_upgrade_banner)

        self.local_section = JobQueueSection("Local (GPU)", self.queue_manager, self.config)
        self.local_section.setLayoutDirection(direction)
        self.local_section.add_media_clicked.connect(lambda: self.add_media("Local (GPU)"))
        self.local_section.download_model_clicked.connect(self.download_local_model)
        self.local_section.abort_job_clicked.connect(self._on_local_job_aborted)
        local_layout.addWidget(self.local_section, 1)

        grid.addWidget(local_container, 0, 0)

        if not DependencyManager.has_local_engine():
            blur = QGraphicsBlurEffect()
            blur.setBlurRadius(10)
            self.local_section.setGraphicsEffect(blur)
            self.local_section.setEnabled(False)

            engine_size = "~2.7 GB" if DependencyManager.has_nvidia_gpu() else "~350 MB"
            self.engine_overlay = DownloadOverlayWidget(
                t("engine_title"), t("engine_desc", size=engine_size), t("engine_btn_download")
            )
            self.engine_overlay.btn_download.clicked.connect(self.start_engine_download)
            grid.addWidget(self.engine_overlay, 0, 0)
        elif DependencyManager.needs_gpu_engine_upgrade():
            self.gpu_upgrade_banner.setVisible(True)

    def _on_local_job_aborted(self, job_id: str):
        local_th = getattr(self, 'local_thread', None)
        if local_th is not None and hasattr(local_th, 'abort_current_job'):
            local_th.abort_current_job(job_id)

    def start_engine_download(self):
        if getattr(self, 'engine_thread', None) is not None and self.engine_thread.isRunning():
            return
        self.engine_overlay.set_downloading()
        self.engine_thread = EngineDownloader()
        self.engine_thread.progress_update.connect(self.engine_overlay.progress.setValue)
        self.engine_thread.status_update.connect(self.engine_overlay.set_status_message)
        self.engine_thread.finished_download.connect(self.on_engine_downloaded)
        self.engine_thread.start()

    def on_engine_downloaded(self, success: bool, message: str):
        if success:
            if getattr(self, 'engine_overlay', None) is not None:
                self.engine_overlay.spinner.stop()
                self.engine_overlay.setVisible(False)
            self.local_section.setGraphicsEffect(None)
            self.local_section.setEnabled(True)
            self.local_section.update_model_button_state()
            if getattr(self, 'gpu_upgrade_banner', None) is not None:
                self.gpu_upgrade_banner.setVisible(DependencyManager.needs_gpu_engine_upgrade())
        else:
            if getattr(self, 'engine_overlay', None) is not None:
                self.engine_overlay.set_error(t("engine_status_failed", message=message))

    def start_gpu_engine_upgrade(self):
        if getattr(self, 'engine_thread', None) is not None and self.engine_thread.isRunning():
            return

        # Refuse upgrade while a local job (pending or active) or model download is running
        has_active_local_job = any(
            j.get("mode") == "Local (GPU)"
            and j.get("status") in ["PENDING", "EXTRACTING", "PROCESSING_LOCAL", "REMUXING"]
            for j in self.queue_manager.get_all_jobs().values()
        )
        model_running = (
            getattr(self, 'model_thread', None) is not None and self.model_thread.isRunning()
        )
        if has_active_local_job or model_running:
            QMessageBox.information(self, t("gpu_banner_busy_title"), t("gpu_banner_busy_msg"))
            return

        self.local_section.setEnabled(False)
        if getattr(self.local_section, 'dropzone_widget', None) is not None:
            self.local_section.dropzone_widget.setEnabled(False)

        self.gpu_upgrade_banner.set_upgrading()
        self.engine_thread = EngineDownloader(upgrade_to_gpu=True)
        self.engine_thread.progress_update.connect(self.gpu_upgrade_banner.set_progress)
        self.engine_thread.status_update.connect(self.gpu_upgrade_banner.set_status_message)
        self.engine_thread.finished_download.connect(self.on_gpu_upgrade_finished)
        self.engine_thread.start()

    def on_gpu_upgrade_finished(self, success: bool, message: str):
        if success:
            self.gpu_upgrade_banner.reset_idle()
            self.gpu_upgrade_banner.setVisible(False)
            self.local_section.setEnabled(True)
            if getattr(self.local_section, 'dropzone_widget', None) is not None:
                self.local_section.dropzone_widget.setEnabled(True)
            self.local_section.update_model_button_state()
            QMessageBox.information(self, t("gpu_banner_success_title"), t("gpu_banner_success_msg"))
        else:
            logger.error(f"GPU engine upgrade failed: {message}")
            engine_still_valid = DependencyManager.has_local_engine()
            if engine_still_valid:
                self.local_section.setEnabled(True)
                if getattr(self.local_section, 'dropzone_widget', None) is not None:
                    self.local_section.dropzone_widget.setEnabled(True)
            display_msg = message
            if "\n" in message or len(message) > 220:
                display_msg, _ = classify_local_error(message)
            self.gpu_upgrade_banner.set_error(
                t("engine_status_failed", message=display_msg),
                allow_dismiss=engine_still_valid,
            )

    def _retire_model_thread(self, thread) -> None:
        if thread is None:
            return
        if getattr(thread, "_ep_retired", False):
            return
        thread._ep_retired = True
        try:
            if thread.isRunning():
                thread.wait(500)
        except Exception:
            pass
        retired = getattr(self, "_retired_model_threads", None)
        if retired is not None:
            try:
                if thread in retired:
                    retired.remove(thread)
            except Exception:
                pass
        try:
            thread.deleteLater()
        except Exception:
            pass

    def download_local_model(self, model_name: str, subfolder: str):
        existing = getattr(self, 'model_thread', None)
        if existing is not None:
            try:
                if existing.isRunning():
                    return
            except RuntimeError:
                self.model_thread = None
            else:
                self._retire_model_thread(existing)
                self.model_thread = None

        friendly_name = self.local_section._get_friendly_model_name()
        self.local_section.set_model_downloading(True)
        self.local_section.set_download_progress(0, friendly_name, "")

        models_dir = os.path.join(self.config.appdata_dir, "models", subfolder)
        os.makedirs(models_dir, exist_ok=True)

        thread = ModelDownloader(model_name, models_dir)
        self.model_thread = thread
        thread.progress_detail.connect(
            lambda pct, speed, th=thread, fn=friendly_name: (
                self.local_section.set_download_progress(pct, fn, speed)
                if self.model_thread is th else None
            )
        )
        thread.finished_download.connect(
            lambda ok, msg, th=thread: self.on_model_downloaded(ok, msg, th)
        )
        try:
            thread.finished.connect(lambda th=thread: self._retire_model_thread(th))
        except Exception:
            pass
        thread.start()

    def on_model_downloaded(self, success: bool, message: str, thread=None):
        active_thread = getattr(self, 'model_thread', None)
        if thread is not None and active_thread is not None and thread is not active_thread:
            return
        finished_thread = thread if thread is not None else active_thread

        raw_details = getattr(finished_thread, "last_error_details", "") if finished_thread else ""
        is_ffmpeg_err = getattr(finished_thread, "last_error_is_ffmpeg", False) if finished_thread else False

        if finished_thread is not None and finished_thread is active_thread:
            self.model_thread = None
            try:
                if finished_thread.isRunning():
                    finished_thread.wait(500)
            except Exception:
                pass
            if not getattr(finished_thread, "_ep_retired", False):
                retired = getattr(self, "_retired_model_threads", None)
                if retired is not None and finished_thread not in retired:
                    retired.append(finished_thread)

        self.local_section.set_model_downloading(False)
        self.local_section.reset_download_progress()
        self.local_section.update_model_button_state()

        if not success:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Critical)
            box.setWindowTitle(t("alert_download_failed_title"))
            box.setText(t("alert_download_failed_msg", message=message))
            if raw_details:
                box.setDetailedText(raw_details)
            box.exec()

            if is_ffmpeg_err or not DependencyManager.has_ffmpeg():
                self.check_ffmpeg()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        overlay = getattr(self, 'ffmpeg_overlay', None)
        if overlay is not None:
            try:
                if overlay.isVisible():
                    cw = self.centralWidget()
                    overlay.resize(cw.size() if cw is not None else self.size())
                    overlay.raise_()
            except RuntimeError:
                self.ffmpeg_overlay = None

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
                self.cloud_thread.verification_warning.connect(self.on_verification_warning)
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
            display_model = "MDX23C" if "MDX23C" in model_selection else ("Kim Vocal 2" if "Kim" in model_selection else "RoFormer")

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
        marker = "\n\n--- Details"
        if marker in error_msg:
            summary, details = error_msg.split(marker, 1)
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Critical)
            box.setWindowTitle(t("alert_job_err_title"))
            box.setText(t("alert_job_err_msg", error=summary.strip()))
            box.setDetailedText(f"--- Details{details}".strip())
            box.exec()
        else:
            QMessageBox.critical(self, t("alert_job_err_title"), t("alert_job_err_msg", error=error_msg))

        if is_ffmpeg_missing_error(error_msg):
            self.check_ffmpeg()

    def on_verification_warning(self, job_id: str, model_name: str, warning_type: str):
        if warning_type == "UNVERIFIED":
            dlg = getattr(self, "_phone_warning_dlg", None)
            try:
                if dlg is not None and dlg.isVisible():
                    dlg.raise_()
                    dlg.activateWindow()
                    return
            except RuntimeError:
                pass

            self._phone_warning_dlg = PhoneVerificationWarningDialog(model_name, self)
            self._phone_warning_dlg.finished.connect(lambda: setattr(self, "_phone_warning_dlg", None))
            self._phone_warning_dlg.show()
        elif warning_type == "TIMEOUT_OR_ERROR":
            if hasattr(self, 'verification_banner'):
                self.verification_banner.show_reminder(model_name)

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
            for rt in list(getattr(self, "_retired_model_threads", []) or []):
                try:
                    if rt is not None and rt.isRunning():
                        threads.append(rt)
                except RuntimeError:
                    pass
            terminate_qt_threads([t for t in threads if t is not None], timeout_ms=1500)
            cleanup_all_subprocesses()
        except Exception:
            pass

        event.accept()
