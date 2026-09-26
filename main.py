import sys
import os
import ctypes
import logging
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTabWidget, QListWidget,
    QProgressBar, QLineEdit, QComboBox, QCheckBox, QMessageBox, QGroupBox, QFormLayout,
    QListWidgetItem, QDialog, QFrame, QGridLayout, QGraphicsBlurEffect,
    QGraphicsDropShadowEffect, QStackedWidget, QSizePolicy, QToolButton
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QSize, QRectF
from PySide6.QtGui import (
    QFont, QColor, QLinearGradient, QPalette, QIcon, QPixmap,
    QPainter, QPainterPath, QPen, QBrush
)

# ─── Windows Taskbar AppUserModelID (Ensures icon appears in Taskbar) ─────────
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("EarPurifier.SproutAudio.Studio.2.0")
except Exception:
    pass

# Ensure current directory is in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from config_manager import ConfigManager
    from queue_manager import QueueManager
    from processor_thread import JobProcessor
    from local_processor import LocalJobProcessor
    from media_engine import get_duration
    from dependency_manager import DependencyManager, FFmpegDownloader, EngineDownloader, ModelDownloader
    from logger_setup import setup_logger
except ImportError:
    from src.config_manager import ConfigManager
    from src.queue_manager import QueueManager
    from src.processor_thread import JobProcessor
    from src.local_processor import LocalJobProcessor
    from src.media_engine import get_duration
    from src.dependency_manager import DependencyManager, FFmpegDownloader, EngineDownloader, ModelDownloader
    from src.logger_setup import setup_logger

# ─── Color Palette (Matches 🌱 Sprout & Wave Calm Theme) ─────────────────────
# Sidebar: Deep botanical forest slate
SIDEBAR_BG = "#0d1a14"
SIDEBAR_BORDER = "#182e23"
SIDEBAR_ITEM_HOVER = "rgba(16, 185, 129, 0.08)"
SIDEBAR_ITEM_ACTIVE = "rgba(16, 185, 129, 0.18)"
SIDEBAR_ACCENT = "#10b981"

# Main Canvas: Calming soft sage off-white
CANVAS_BG = "#f4f8f5"
CARD_BG = "#ffffff"
CARD_BORDER = "#dfebe4"
CARD_BORDER_HOVER = "#bad4c7"

# Typography: Deep forest charcoal & slate
TEXT_HEAD = "#0b2318"        # Deep botanical slate
TEXT_BODY = "#233d30"        # Crisp readable body
TEXT_MUTED = "#557364"       # Gentle sage secondary text
TEXT_FAINT = "#86a193"       # Subtle timestamps & borders

# Accents inspired by the Sprout & Wave icon
ACCENT_EMERALD = "#10b981"   # Vibrant fresh sprout green
ACCENT_MINT = "#34d399"      # Light fresh mint
ACCENT_TEAL = "#0d9488"      # Deep tranquil teal
ACCENT_CYAN = "#06b6d4"      # Acoustic soundwave cyan
ACCENT_BLUE = "#0284c7"      # In Progress blue
ACCENT_AMBER = "#f59e0b"     # Warning amber
ACCENT_RED = "#ef4444"       # Destructive red

# ─── Asset Helper ─────────────────────────────────────────────────────────────
def get_asset_path(filename: str) -> str:
    """Get absolute path to asset file, works for dev and PyInstaller onefile."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_dir = os.path.join(sys._MEIPASS, "src", "assets")
        if not os.path.exists(base_dir):
            base_dir = os.path.join(sys._MEIPASS, "assets")
    else:
        base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    return os.path.join(base_dir, filename)


# ─── Clean '✕' Mark Button (NO TRASH CONCEPT) ─────────────────────────────────
class CleanCloseButton(QPushButton):
    """
    Sleek minimalist circular '✕' button for removing jobs from history.
    Painted via QPainter with antialiasing and soft red circular hover ring.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Remove from history")
        self._hovered = False

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self._hovered:
            painter.setBrush(QColor(239, 68, 68, 22))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))

        color = QColor(ACCENT_RED) if self._hovered else QColor(TEXT_FAINT)
        pen = QPen(color, 1.8, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)

        cx, cy = self.width() // 2, self.height() // 2
        d = 4
        painter.drawLine(cx - d, cy - d, cx + d, cy + d)
        painter.drawLine(cx + d, cy - d, cx - d, cy + d)


class VectorAlertBadge(QWidget):
    """
    Circular alert badge with a clean '✕' mark for confirmation dialogs.
    Zero trash concept.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(48, 48)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setBrush(QColor(239, 68, 68, 18))
        painter.setPen(QPen(QColor(239, 68, 68, 50), 1))
        painter.drawEllipse(self.rect().adjusted(2, 2, -2, -2))

        pen = QPen(QColor(ACCENT_RED), 2.4, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)

        cx, cy = self.width() // 2, self.height() // 2
        d = 7
        painter.drawLine(cx - d, cy - d, cx + d, cy + d)
        painter.drawLine(cx + d, cy - d, cx - d, cy + d)


class SidebarLogo(QWidget):
    """
    Native squircle logo display without any artificial enclosing boxes or frames.
    Directly renders the smooth Sprout & Wave icon.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(48, 48)
        self.logo_path = get_asset_path("logo.png")
        self.pixmap = None
        if os.path.exists(self.logo_path):
            self.pixmap = QPixmap(self.logo_path)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        rect = self.rect().adjusted(1, 1, -1, -1)
        if self.pixmap and not self.pixmap.isNull():
            painter.drawPixmap(rect, self.pixmap)
        else:
            # Tranquil botanical sprout fallback
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0, QColor(ACCENT_EMERALD))
            grad.setColorAt(1, QColor(ACCENT_TEAL))
            painter.setBrush(grad)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 10, 10)


class SidebarNavButton(QPushButton):
    """
    Vertical rail navigation button with vector icon and clean text label.
    """
    def __init__(self, icon_type: str, label_text: str, parent=None):
        super().__init__(parent)
        self.icon_type = icon_type
        self.label_text = label_text
        self.is_active = False
        self._hovered = False
        self.setFixedHeight(56)
        self.setFixedWidth(62)
        self.setCursor(Qt.PointingHandCursor)

    def set_active(self, active: bool):
        self.is_active = active
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(4, 2, -4, -2)

        if self.is_active:
            painter.setBrush(QColor(16, 185, 129, 38))
            painter.setPen(QPen(QColor(16, 185, 129, 70), 1))
            painter.drawRoundedRect(rect, 8, 8)
            # Left active indicator pill
            painter.setBrush(QColor(ACCENT_EMERALD))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(0, 14, 3, 28, 1.5, 1.5)
        elif self._hovered:
            painter.setBrush(QColor(255, 255, 255, 12))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 8, 8)

        if self.is_active:
            icon_color = QColor("#ffffff")
            text_color = QColor("#ffffff")
        elif self._hovered:
            icon_color = QColor("#e2ede7")
            text_color = QColor("#e2ede7")
        else:
            icon_color = QColor(TEXT_FAINT)
            text_color = QColor(TEXT_FAINT)

        pen = QPen(icon_color, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        cx, cy = self.width() // 2, 19

        if self.icon_type == "cloud":
            cloud = QPainterPath()
            cloud.moveTo(cx - 9, cy + 3)
            cloud.arcTo(cx - 13, cy - 3, 8, 8, 180, 180)
            cloud.arcTo(cx - 7, cy - 8, 12, 12, 140, 180)
            cloud.arcTo(cx + 3, cy - 4, 8, 8, 90, 180)
            cloud.lineTo(cx - 9, cy + 3)
            painter.drawPath(cloud)
        elif self.icon_type == "local":
            painter.drawRoundedRect(cx - 8, cy - 8, 16, 16, 3, 3)
            painter.drawRoundedRect(cx - 4, cy - 4, 8, 8, 1, 1)
            painter.drawLine(cx - 5, cy - 10, cx - 5, cy - 8)
            painter.drawLine(cx, cy - 10, cx, cy - 8)
            painter.drawLine(cx + 5, cy - 10, cx + 5, cy - 8)
            painter.drawLine(cx - 5, cy + 8, cx - 5, cy + 10)
            painter.drawLine(cx, cy + 8, cx, cy + 10)
            painter.drawLine(cx + 5, cy + 8, cx + 5, cy + 10)
        elif self.icon_type == "settings":
            painter.drawEllipse(cx - 4, cy - 4, 8, 8)
            for angle in [0, 45, 90, 135]:
                painter.drawLine(cx - 7, cy, cx + 7, cy)
                painter.drawLine(cx, cy - 7, cx, cy + 7)

        painter.setPen(text_color)
        font = QFont("Segoe UI", 9, QFont.Bold if self.is_active else QFont.DemiBold)
        painter.setFont(font)
        painter.drawText(0, 35, self.width(), 16, Qt.AlignCenter, self.label_text)


# ─── Settings Dialog ─────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Settings - EarPurifier")
        self.setMinimumWidth(520)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: #ffffff;
            }}
            QGroupBox {{
                font-weight: 700;
                font-size: 13px;
                color: {TEXT_HEAD};
                border: 1px solid {CARD_BORDER};
                border-radius: 8px;
                margin-top: 14px;
                padding-top: 18px;
                background-color: #ffffff;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 6px;
                color: {TEXT_HEAD};
            }}
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
            QComboBox {{
                background-color: #f7faf8;
                border: 1px solid {CARD_BORDER};
                border-radius: 6px;
                padding: 8px 12px;
                color: {TEXT_HEAD};
                font-size: 12px;
            }}
            QComboBox:focus {{
                border-color: {ACCENT_EMERALD};
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
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 22, 24, 22)

        title_box = QHBoxLayout()
        lbl_title = QLabel("⚙  Application Settings")
        lbl_title.setStyleSheet(f"font-size: 18px; font-weight: 800; color: {TEXT_HEAD}; background: transparent;")
        title_box.addWidget(lbl_title)
        layout.addLayout(title_box)

        grp_kaggle = QGroupBox("Kaggle Cloud Credentials")
        form_kaggle = QFormLayout()
        form_kaggle.setSpacing(10)
        form_kaggle.setContentsMargins(14, 16, 14, 14)
        self.inp_user = QLineEdit(self.config.get("kaggle_username"))
        self.inp_user.setPlaceholderText("your_kaggle_username")
        self.inp_key = QLineEdit(self.config.get("kaggle_api_key"))
        self.inp_key.setEchoMode(QLineEdit.Password)
        self.inp_key.setPlaceholderText("••••••••••••••••")
        form_kaggle.addRow("Kaggle Username:", self.inp_user)
        form_kaggle.addRow("Kaggle API Key:", self.inp_key)
        grp_kaggle.setLayout(form_kaggle)

        grp_general = QGroupBox("General & Engine Settings")
        form_general = QFormLayout()
        form_general.setSpacing(10)
        form_general.setContentsMargins(14, 16, 14, 14)

        out_layout = QHBoxLayout()
        out_layout.setSpacing(8)
        self.inp_out = QLineEdit(self.config.get("output_folder"))
        self.inp_out.setPlaceholderText("Select folder...")
        btn_browse = QPushButton("Browse")
        btn_browse.setCursor(Qt.PointingHandCursor)
        btn_browse.setStyleSheet(f"""
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
        btn_browse.clicked.connect(self.browse_output)
        out_layout.addWidget(self.inp_out)
        out_layout.addWidget(btn_browse)
        form_general.addRow("Output Folder:", out_layout)

        self.cmb_model = QComboBox()
        self.cmb_model.addItems([
            "SOTA (RoFormer) - Requires High-End GPU",
            "Mid (MDX23C) - Balanced Quality & Speed",
            "Low (MDXNET) - Fast & Low VRAM"
        ])
        self.cmb_model.setCurrentText(self.config.get("local_model"))
        form_general.addRow("Local AI Model:", self.cmb_model)

        self.chk_logging = QCheckBox("Enable Background Logging (Recommended)")
        self.chk_logging.setChecked(self.config.get("enable_logging"))
        form_general.addRow("", self.chk_logging)
        grp_general.setLayout(form_general)

        btn_save = QPushButton("Save Settings")
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.setStyleSheet(f"""
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
        btn_save.clicked.connect(self.accept)

        layout.addWidget(grp_kaggle)
        layout.addWidget(grp_general)
        layout.addSpacing(6)
        layout.addWidget(btn_save)

    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.inp_out.setText(folder)

    def save_and_get_config(self):
        self.config.set("kaggle_username", self.inp_user.text().strip())
        self.config.set("kaggle_api_key", self.inp_key.text().strip())
        self.config.set("output_folder", self.inp_out.text().strip())
        self.config.set("local_model", self.cmb_model.currentText())
        self.config.set("enable_logging", self.chk_logging.isChecked())
        return True


# ─── Delete Confirmation Dialog (CLEAN, NO HIGHLIGHT, NO TRASH CONCEPT) ──────
class DeleteConfirmDialog(QDialog):
    def __init__(self, count: int, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Confirm Removal")
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
        msg = f"Remove {count} job(s) from history?" if count > 1 else "Remove this job from history?"
        lbl_msg = QLabel(msg)
        lbl_msg.setStyleSheet(f"font-size: 15px; font-weight: 800; color: {TEXT_HEAD}; background: transparent; border: none;")
        msg_box.addWidget(lbl_msg)

        lbl_desc = QLabel("This will remove the selected entry from your session history.")
        lbl_desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent; border: none;")
        msg_box.addWidget(lbl_desc)
        top_row.addLayout(msg_box)
        top_row.addStretch()
        layout.addLayout(top_row)

        layout.addSpacing(4)

        self.chk_delete_files = QCheckBox("Delete local output file(s) too")
        self.chk_delete_files.setToolTip("Will only delete generated/purified video files, never original inputs.")
        self.chk_delete_files.setChecked(self.config.get("delete_output_files", False))
        layout.addWidget(self.chk_delete_files)

        lbl_note = QLabel("Note: Original input video files will never be touched.")
        lbl_note.setStyleSheet(f"color: {TEXT_FAINT}; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(lbl_note)

        layout.addSpacing(6)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_cancel = QPushButton("Cancel")
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

        btn_delete = QPushButton("Remove")
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


# ─── Job Row Widget (Calm & Polished SaaS Row) ────────────────────────────────
class JobWidget(QWidget):
    delete_requested = Signal(str)
    abort_requested = Signal(str)
    selection_changed = Signal(str, bool)

    def __init__(self, job_id: str, job_dict: dict, mode: str = "Cloud (Kaggle)", parent=None):
        super().__init__(parent)
        self.job_id = job_id
        self.job_dict = job_dict
        self.video_path = job_dict.get("original_video", "")
        self.duration = job_dict.get("duration", 0.0)
        self.mode = mode
        self.current_status = "PENDING"
        self.remaining_seconds = 0
        
        # Calculate elapsed seconds ignoring the PENDING wait time
        from datetime import datetime, timezone
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
        except:
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
        self.chk_select.stateChanged.connect(lambda state: self.selection_changed.emit(self.job_id, state == Qt.Checked.value))
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
            # Fallback for older jobs
            model_name = "Kaggle T4" if "Cloud" in mode else "RoFormer"
        
        mode_prefix = "Cloud" if "Cloud" in mode else "Local"
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
        initial_elapsed = f"{emins}m {esecs}s" if emins > 0 else f"{esecs}s"
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
        self.lbl_badge = QLabel("QUEUED")
        self._set_badge_style("queued")
        top_row.addWidget(self.lbl_badge)

        # Abort Button (when active)
        self.btn_abort = QPushButton("⏹ Abort")
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
        self.btn_abort.clicked.connect(lambda: self.abort_requested.emit(self.job_id))
        top_row.addWidget(self.btn_abort)

        # Clean '✕' Button (NO TRASH ICON!)
        self.btn_delete = CleanCloseButton()
        self.btn_delete.clicked.connect(lambda: self.delete_requested.emit(self.job_id))
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
        if state == "running":
            self.lbl_badge.setText("IN PROGRESS")
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
            self.lbl_badge.setText("COMPLETED")
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
            self.lbl_badge.setText("ABORTED")
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
            self.lbl_badge.setText("FAILED")
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
            self.lbl_badge.setText("QUEUED")
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
        self.tag_elapsed.setText(f"{emins}m {esecs}s" if emins > 0 else f"{esecs}s")

        # ETA Logic (Cloud only)
        if self.mode == "Cloud (Kaggle)":
            if self.current_status in ["PENDING", "EXTRACTING", "UPLOADING"]:
                self.lbl_eta.setText("ETA: Calculating...")
            elif self.current_status in ["PROCESSING_CLOUD", "DOWNLOADING", "REMUXING"]:
                if not getattr(self, "eta_initialized", False):
                    # Initialize ETA when Kaggle actually starts processing (Adjusted to be more realistic)
                    self.remaining_seconds = max(60, int(150 + (self.duration * 1.5)))
                    self.eta_initialized = True
                
                self.remaining_seconds -= 1
                if self.remaining_seconds > 0:
                    mins, secs = divmod(self.remaining_seconds, 60)
                    self.lbl_eta.setText(f"ETA: ~{mins}m {secs}s" if mins > 0 else f"ETA: ~{secs}s")
                else:
                    self.lbl_eta.setText("ETA: Anytime now...")

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
            self.lbl_message.setText("Purification complete · Audio isolated")
            self.progress.setVisible(False)
        elif status == "ABORTED":
            self.timer.stop()
            self._set_badge_style("aborted")
            if self.mode == "Cloud (Kaggle)":
                self.lbl_eta.setVisible(False)
            self.lbl_message.setText("Job aborted")
            self.progress.setVisible(False)
        elif status in ["ERROR", "FAILED"]:
            self.timer.stop()
            self._set_badge_style("failed")
            if self.mode == "Cloud (Kaggle)":
                self.lbl_eta.setVisible(False)
            self.lbl_message.setText("Processing failed")
            self.progress.setVisible(False)
        elif status == "PENDING":
            self._set_badge_style("queued")
            if self.mode == "Cloud (Kaggle)":
                self.lbl_eta.setVisible(True)
                self.lbl_eta.setText("In Queue")
            self.lbl_message.setText("Waiting in queue...")
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
        else:
            self._set_badge_style("running")
            if self.mode == "Cloud (Kaggle)":
                self.lbl_eta.setVisible(True)
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
            if not self.lbl_message.text() or self.lbl_message.text() == "Waiting in queue...":
                self.lbl_message.setText("Isolating vocals with AI...")

    def update_message(self, message: str):
        self.lbl_message.setText(message)


# ─── Group Header Widget (ClickUp Category Pills) ────────────────────────────
class StatusGroupHeader(QWidget):
    def __init__(self, title: str, count: int, color_hex: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 14, 8, 6)
        layout.setSpacing(8)

        lbl_pill = QLabel(f" {title.upper()}  {count} ")
        lbl_pill.setStyleSheet(f"""
            background-color: {color_hex};
            color: #ffffff;
            font-size: 11px;
            font-weight: 800;
            padding: 3px 10px;
            border-radius: 11px;
            letter-spacing: 0.5px;
        """)
        layout.addWidget(lbl_pill)
        layout.addStretch()


# ─── Job Queue Section (Reusable Engine Canvas) ───────────────────────────────
class JobQueueSection(QWidget):
    add_video_clicked = Signal()
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

        # Primary Action Button: '+ Add Video' (Sprout-Teal Gradient)
        self.btn_add = QPushButton("＋ Add Video")
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {ACCENT_EMERALD}, stop:1 {ACCENT_TEAL});
                color: #ffffff;
                font-weight: 800;
                font-size: 13px;
                padding: 9px 22px;
                border-radius: 8px;
                border: none;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {ACCENT_MINT}, stop:1 #0f766e);
            }}
        """)
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
        self.cmb_filter.setStyleSheet(f"""
            QComboBox {{
                background-color: #ffffff;
                border: 1px solid {CARD_BORDER};
                border-radius: 7px;
                padding: 6px 28px 6px 12px;
                color: {TEXT_HEAD};
                font-weight: 600;
                font-size: 12px;
                min-width: 140px;
            }}
            QComboBox:hover {{
                border-color: {ACCENT_EMERALD};
                background-color: #ffffff;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border: none;
                background: transparent;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {TEXT_MUTED};
                margin-right: 8px;
            }}
            QComboBox QAbstractItemView {{
                background-color: #ffffff;
                border: 1px solid {CARD_BORDER};
                border-radius: 8px;
                selection-background-color: #ecfdf5;
                selection-color: {ACCENT_EMERALD};
                color: {TEXT_HEAD};
                padding: 4px;
                outline: 0px;
            }}
            QComboBox QAbstractItemView::item {{
                height: 28px;
                padding-left: 8px;
                border-radius: 4px;
            }}
        """)
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
        import webbrowser
        btn_mariam.clicked.connect(lambda: webbrowser.open('https://t.me/MariamInitiative'))
        views_bar.addWidget(btn_mariam)

        main_layout.addLayout(views_bar)

        # ── 3. Batch Action Bar ──
        self.batch_bar = QFrame()
        self.batch_bar.setStyleSheet(f"""
            QFrame {{
                background-color: #ecfdf5;
                border: 1px solid #a7f3d0;
                border-radius: 8px;
            }}
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
            QScrollBar:vertical {{
                background: #edf5f0;
                width: 8px;
                border-radius: 4px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: #c2d9cc;
                border-radius: 4px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {TEXT_FAINT};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
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

            lbl_empty_desc = QLabel("Click '+ Add Video' above to upload video files and isolate vocals with AI.")
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

        widget.delete_requested.connect(self.on_delete_single)
        widget.abort_requested.connect(self.on_abort_job)
        widget.selection_changed.connect(lambda _jid, _chk: self.update_selected_count())

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
        if dlg.exec() == QDialog.Accepted:
            self.queue_manager.delete_job(job_id, delete_output=dlg.should_delete_files())
            self.refresh_list()

    def on_delete_selected(self):
        selected_ids = [jid for jid, w in self.job_widgets.items() if w.is_selected()]
        if not selected_ids:
            QMessageBox.information(self, "No Selection", "Please select at least one job to delete.")
            return

        dlg = DeleteConfirmDialog(len(selected_ids), self.config, self)
        if dlg.exec() == QDialog.Accepted:
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
        if dlg.exec() == QDialog.Accepted:
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
            self.btn_add.setText("＋ Add Video")
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
            self.add_video_clicked.emit()


# ─── Main Window ─────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EarPurifier - AI Audio Isolation Studio")
        self.setMinimumSize(980, 680)

        # Set Window and Application Icon (Multi-resolution .ico/.png)
        logo_ico = get_asset_path("logo.ico")
        logo_png = get_asset_path("logo.png")
        if os.path.exists(logo_ico):
            self.setWindowIcon(QIcon(logo_ico))
        elif os.path.exists(logo_png):
            self.setWindowIcon(QIcon(logo_png))

        self.config = ConfigManager()
        setup_logger(self.config)
        
        # Cleanup any orphaned temp files from previous crashed runs
        import shutil
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
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── 1. Left Vertical Navigation Rail (Botanical Dark Slate) ──
        rail = QWidget()
        rail.setFixedWidth(72)
        rail.setStyleSheet(f"""
            QWidget {{
                background-color: {SIDEBAR_BG};
                border-right: 1px solid {SIDEBAR_BORDER};
            }}
        """)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(8, 16, 8, 16)
        rail_layout.setSpacing(14)
        rail_layout.setAlignment(Qt.AlignHCenter)

        # Native Sprout Logo without any artificial boxes/frames
        self.logo_widget = SidebarLogo()
        self.logo_widget.setToolTip("EarPurifier - Serene AI Audio Isolation")
        rail_layout.addWidget(self.logo_widget, 0, Qt.AlignCenter)

        rail_layout.addSpacing(10)

        self.btn_nav_cloud = SidebarNavButton("cloud", "Cloud")
        self.btn_nav_cloud.setToolTip("Cloud Processing (Free Kaggle GPUs)")
        self.btn_nav_cloud.clicked.connect(lambda: self.switch_view(0))
        rail_layout.addWidget(self.btn_nav_cloud)

        self.btn_nav_local = SidebarNavButton("local", "Local")
        self.btn_nav_local.setToolTip("Local Processing (Hardware GPU)")
        self.btn_nav_local.clicked.connect(lambda: self.switch_view(1))
        rail_layout.addWidget(self.btn_nav_local)

        rail_layout.addStretch()

        self.btn_nav_settings = SidebarNavButton("settings", "Settings")
        self.btn_nav_settings.setToolTip("Settings & Credentials")
        self.btn_nav_settings.clicked.connect(self.open_settings)
        rail_layout.addWidget(self.btn_nav_settings)

        # Status Dot (Pulsing Emerald Green)
        dot_box = QHBoxLayout()
        dot_box.setAlignment(Qt.AlignCenter)
        lbl_dot = QLabel("●")
        lbl_dot.setStyleSheet(f"color: {ACCENT_EMERALD}; font-size: 11px; background: transparent; border: none;")
        lbl_dot.setToolTip("EarPurifier Engine Ready")
        dot_box.addWidget(lbl_dot)
        rail_layout.addLayout(dot_box)

        root_layout.addWidget(rail)

        # ── 2. Main Stacked Workspace Canvas ──
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background-color: {CANVAS_BG};")

        self.cloud_section = JobQueueSection("Cloud (Kaggle)", self.queue_manager, self.config)
        self.cloud_section.add_video_clicked.connect(lambda: self.add_video("Cloud (Kaggle)"))
        self.stack.addWidget(self.cloud_section)

        self.tab_local = QWidget()
        self.setup_local_tab()
        self.stack.addWidget(self.tab_local)

        root_layout.addWidget(self.stack, 1)

        self.switch_view(0)

        self.setStyleSheet(f"""
            * {{
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, 'Inter', Roboto, sans-serif;
            }}
            QMainWindow {{
                background-color: {CANVAS_BG};
            }}
        """)
        
        self.check_ffmpeg()

    def check_ffmpeg(self):
        if not DependencyManager.has_ffmpeg():
            # Create a full-screen overlay over the central widget
            self.ffmpeg_overlay = QWidget(self.centralWidget())
            self.ffmpeg_overlay.setStyleSheet("background-color: rgba(244, 248, 245, 235);")
            
            # Position it to cover everything
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

            lbl_title = QLabel("FFmpeg & FFprobe Not Installed")
            lbl_title.setStyleSheet(f"font-size: 18px; font-weight: 800; color: {TEXT_HEAD}; border: none; background: transparent;")
            lbl_title.setAlignment(Qt.AlignCenter)
            wb_layout.addWidget(lbl_title)

            lbl_sub = QLabel("EarPurifier checked your System PATH and AppData bin folder but could not find these required tools. They are needed to extract and rebuild media files.")
            lbl_sub.setWordWrap(True)
            lbl_sub.setStyleSheet(f"font-size: 13px; color: {TEXT_MUTED}; border: none; background: transparent;")
            lbl_sub.setAlignment(Qt.AlignCenter)
            wb_layout.addWidget(lbl_sub)
            
            self.ffmpeg_progress = QProgressBar()
            self.ffmpeg_progress.setVisible(False)
            wb_layout.addWidget(self.ffmpeg_progress)
            
            self.ffmpeg_status = QLabel("")
            self.ffmpeg_status.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; border: none; background: transparent;")
            self.ffmpeg_status.setAlignment(Qt.AlignCenter)
            self.ffmpeg_status.setVisible(False)
            wb_layout.addWidget(self.ffmpeg_status)

            self.btn_download_ffmpeg = QPushButton("Download Automatically")
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
            
            # Disable main UI interactions behind the overlay
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
            self.ffmpeg_status.setText(f"Failed: {message}")
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

        self.local_section = JobQueueSection("Local (GPU)", self.queue_manager, self.config)
        self.local_section.add_video_clicked.connect(lambda: self.add_video("Local (GPU)"))
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

            lbl_title = QLabel("Engine Required")
            lbl_title.setStyleSheet(f"font-size: 18px; font-weight: 800; color: {TEXT_HEAD}; border: none; background: transparent;")
            lbl_title.setAlignment(Qt.AlignCenter)
            wb_layout.addWidget(lbl_title)

            lbl_sub = QLabel("To process audio completely offline on your own hardware, EarPurifier needs to download a portable AI engine (~2.5GB).")
            lbl_sub.setWordWrap(True)
            lbl_sub.setStyleSheet(f"font-size: 13px; color: {TEXT_MUTED}; border: none; background: transparent;")
            lbl_sub.setAlignment(Qt.AlignCenter)
            wb_layout.addWidget(lbl_sub)
            
            self.engine_progress = QProgressBar()
            self.engine_progress.setVisible(False)
            wb_layout.addWidget(self.engine_progress)
            
            self.engine_status = QLabel("")
            self.engine_status.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; border: none; background: transparent;")
            self.engine_status.setAlignment(Qt.AlignCenter)
            self.engine_status.setVisible(False)
            wb_layout.addWidget(self.engine_status)

            self.btn_download_engine = QPushButton("Download & Install Automatically")
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
            self.engine_status.setText(f"Failed: {message}")
            self.engine_status.setStyleSheet("color: #ef4444; font-size: 11px;")

    def download_local_model(self, model_name: str, subfolder: str):
        self.local_section.btn_add.setEnabled(False)
        self.local_section.btn_add.setText(f"⬇ Downloading...")
        
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
            QMessageBox.critical(self, "Download Failed", f"Failed to download AI model:\n{message}")
            self.local_section.btn_add.setEnabled(True)
            self.local_section.update_model_button_state()

    def open_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() == QDialog.Accepted:
            dlg.save_and_get_config()
            setup_logger(self.config)
            QMessageBox.information(self, "Saved", "Settings saved successfully!")
            self.init_threads()
            if hasattr(self, 'local_section'):
                self.local_section.update_model_button_state()

    def init_threads(self):
        # Do not block the UI by waiting for threads to stop.
        # Threads read config dynamically.
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
        if mode == "Cloud (Kaggle)" and not self.config.get("kaggle_username"):
            QMessageBox.warning(self, "Missing Credentials", "Please set your Kaggle Username and API Key in Settings first.")
            self.open_settings()
            return

        # Pre-flight check: Verify and create output directory upfront to catch Windows Defender / permission issues early!
        try:
            out_dir = self.config.get_output_folder(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            if not os.path.exists(out_dir):
                os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "Permission Denied", f"Could not create output folder. Windows Defender or an antivirus might be blocking access.\n\nError: {e}\n\nPlease change the output folder in Settings to your Desktop.")
            return

        files, _ = QFileDialog.getOpenFileNames(self, "Select Video Files", "", "Video Files (*.mp4 *.mkv *.avi *.mov)")
        
        model_selection = self.config.get("local_model", "")
        if "RoFormer" in model_selection:
            display_model = "RoFormer"
        elif "MDX23C" in model_selection:
            display_model = "MDX23C"
        else:
            display_model = "Kim Vocal 2"
            
        for file in files:
            # We defer duration extraction to the background thread to prevent UI freezing
            duration = 0.0
            jid = self.queue_manager.add_job(file, mode=mode, duration=duration, model=display_model)

        if mode == "Cloud (Kaggle)":
            self.cloud_section.refresh_list()
        else:
            self.local_section.refresh_list()

    def on_job_error(self, jid: str, error_msg: str):
        QMessageBox.critical(self, "Job Error", f"An error occurred in job:\n{error_msg}")

    def closeEvent(self, event):
        if hasattr(self, 'cloud_thread'):
            self.cloud_thread.stop()
        if hasattr(self, 'local_thread'):
            self.local_thread.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    logo_ico = get_asset_path("logo.ico")
    logo_png = get_asset_path("logo.png")
    if os.path.exists(logo_ico):
        app.setWindowIcon(QIcon(logo_ico))
    elif os.path.exists(logo_png):
        app.setWindowIcon(QIcon(logo_png))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
