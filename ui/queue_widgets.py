from PySide6.QtWidgets import (
    QWidget, QFrame, QPushButton, QHBoxLayout, QVBoxLayout, QLabel,
    QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor, QPainter, QPen

from .theme import Theme, ThemeMode
try:
    from i18n import t, is_rtl, format_jobs_count
except ImportError:
    from src.i18n import t, is_rtl, format_jobs_count


# ─── Segmented Pill Switcher ──────────────────────────────────────────────────

class SegmentedPillSwitcher(QFrame):
    """Modern inline segmented capsule control: [ All 3 | In Progress 1 | Completed 2 ]."""
    currentIndexChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("segmentedSwitcher")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.current_index = 0
        self.counts = [0, 0, 0]
        self.setFixedHeight(30)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self.btn_all = QPushButton()
        self.btn_active = QPushButton()
        self.btn_completed = QPushButton()
        self.buttons = [self.btn_all, self.btn_active, self.btn_completed]

        for idx, btn in enumerate(self.buttons):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(26)
            btn.clicked.connect(lambda _chk=False, i=idx: self.set_current_index(i))
            layout.addWidget(btn)

        self.update_style()
        self.update_labels()

    def set_current_index(self, index: int):
        if index != self.current_index:
            self.current_index = index
            self.update_style()
            self.currentIndexChanged.emit(index)

    def set_counts(self, all_count: int, active_count: int, completed_count: int):
        self.counts = [all_count, active_count, completed_count]
        self.update_labels()

    def update_labels(self):
        labels = [
            f"{t('tab_all')} {self.counts[0]}",
            f"{t('tab_in_progress')} {self.counts[1]}",
            f"{t('tab_completed')} {self.counts[2]}"
        ]
        for btn, lbl in zip(self.buttons, labels):
            btn.setText(lbl)

    def update_style(self):
        mode = Theme.get_mode()
        container_bg = Theme.get_token("CARD_BG", mode)
        container_border = Theme.get_token("CARD_BORDER", mode)
        accent = Theme.get_token("ACCENT_EMERALD", mode)
        text_muted = Theme.get_token("TEXT_MUTED", mode)
        text_head = Theme.get_token("TEXT_HEAD", mode)

        self.setStyleSheet(f"""
            QFrame#segmentedSwitcher {{
                background-color: {container_bg};
                border: 1px solid {container_border};
                border-radius: 8px;
            }}
        """)

        for idx, btn in enumerate(self.buttons):
            if idx == self.current_index:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {accent};
                        color: #ffffff;
                        font-weight: 800;
                        font-size: 11.5px;
                        padding: 4px 12px;
                        border-radius: 6px;
                        border: none;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent;
                        color: {text_muted};
                        font-weight: 600;
                        font-size: 11.5px;
                        padding: 4px 12px;
                        border-radius: 6px;
                        border: none;
                    }}
                    QPushButton:hover {{
                        color: {text_head};
                        background-color: rgba(16, 185, 129, 0.08);
                    }}
                """)


# ─── Floating Batch Action Dock ───────────────────────────────────────────────

class FloatingBatchDock(QWidget):
    """Floating action dock anchored at bottom center with shadow elevation."""
    sig_select_all = Signal()
    sig_cancel = Signal()
    sig_delete = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(12)

        self.dot = QLabel("●")
        self.dot.setStyleSheet("color: #10b981; font-size: 10px; background: transparent;")
        layout.addWidget(self.dot)

        self.lbl_count = QLabel(format_jobs_count(0))
        self.lbl_count.setStyleSheet("font-weight: 800; font-size: 12px; background: transparent;")
        layout.addWidget(self.lbl_count)

        sep = QLabel("|")
        sep.setStyleSheet("color: rgba(120, 150, 130, 0.5); background: transparent;")
        layout.addWidget(sep)

        self.btn_all = QPushButton(t("btn_select_all"))
        self.btn_all.setCursor(Qt.PointingHandCursor)
        self.btn_all.clicked.connect(self.sig_select_all.emit)
        layout.addWidget(self.btn_all)

        self.btn_cancel = QPushButton(t("btn_cancel"))
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.sig_cancel.emit)
        layout.addWidget(self.btn_cancel)

        self.btn_delete = QPushButton(t("btn_remove_selected"))
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.clicked.connect(self.sig_delete.emit)
        layout.addWidget(self.btn_delete)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(16)
        shadow.setColor(QColor(0, 0, 0, 45))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

        self.update_style()

    def set_count(self, count: int):
        self.lbl_count.setText(format_jobs_count(count))

    def update_style(self):
        mode = Theme.get_mode()
        dock_bg = Theme.get_token("DOCK_BG", mode)
        dock_border = Theme.get_token("DOCK_BORDER", mode)
        text_head = Theme.get_token("TEXT_HEAD", mode)
        text_muted = Theme.get_token("TEXT_MUTED", mode)

        self.setStyleSheet(f"""
            FloatingBatchDock {{
                background-color: {dock_bg};
                border: 1px solid {dock_border};
                border-radius: 12px;
            }}
            QLabel {{
                color: {text_head};
            }}
            QPushButton {{
                background: transparent;
                color: {text_muted};
                font-weight: 600;
                font-size: 11.5px;
                padding: 4px 8px;
                border-radius: 4px;
                border: none;
            }}
            QPushButton:hover {{
                color: {text_head};
                background: rgba(16, 185, 129, 0.1);
            }}
            QPushButton#btnDeleteSelected {{
                background-color: #ef4444;
                color: #ffffff;
                font-weight: 700;
                padding: 5px 14px;
                border-radius: 6px;
            }}
            QPushButton#btnDeleteSelected:hover {{
                background-color: #dc2626;
            }}
        """)
        self.btn_delete.setObjectName("btnDeleteSelected")


# ─── Dashed Dropzone Empty State ──────────────────────────────────────────────

class DropZoneWidget(QWidget):
    """Dashed dropzone empty state with vector audio waveform and format pills."""
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(170)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(20, 24, 20, 24)
        layout.setSpacing(6)

        self.lbl_title = QLabel(t("dropzone_title"))
        self.lbl_title.setStyleSheet("font-size: 13.5px; font-weight: 800; background: transparent;")
        self.lbl_title.setAlignment(Qt.AlignCenter)

        self.lbl_desc = QLabel(t("dropzone_desc"))
        self.lbl_desc.setStyleSheet("font-size: 11px; color: #749683; background: transparent;")
        self.lbl_desc.setAlignment(Qt.AlignCenter)

        pills_box = QHBoxLayout()
        pills_box.setAlignment(Qt.AlignCenter)
        pills_box.setSpacing(5)
        for fmt in ["MP4", "MKV", "FLAC", "WAV", "MP3", "AAC", "OPUS"]:
            lbl_p = QLabel(fmt)
            lbl_p.setStyleSheet("""
                font-family: Consolas, monospace;
                font-size: 9.5px;
                font-weight: 700;
                color: #10b981;
                background: rgba(16, 185, 129, 0.1);
                border: 1px solid rgba(16, 185, 129, 0.25);
                border-radius: 4px;
                padding: 1px 5px;
            """)
            pills_box.addWidget(lbl_p)

        self.lbl_more_formats = QLabel(t("dropzone_more_formats"))
        self.lbl_more_formats.setStyleSheet("""
            font-size: 9.5px;
            font-weight: 700;
            color: #10b981;
            background: rgba(16, 185, 129, 0.06);
            border: 1px dashed rgba(16, 185, 129, 0.35);
            border-radius: 4px;
            padding: 1px 7px;
        """)
        pills_box.addWidget(self.lbl_more_formats)

        layout.addSpacing(28)
        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_desc)
        layout.addSpacing(4)
        layout.addLayout(pills_box)

    def retranslate_ui(self):
        self.lbl_title.setText(t("dropzone_title"))
        self.lbl_desc.setText(t("dropzone_desc"))
        self.lbl_more_formats.setText(t("dropzone_more_formats"))

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        mode = Theme.get_mode()
        border_color = QColor(Theme.get_token("CARD_BORDER", mode))
        bg_color = QColor(Theme.get_token("CARD_BG", mode))

        rect = self.rect().adjusted(2, 2, -2, -2)
        pen = QPen(border_color, 1.8, Qt.DashLine)
        pen.setDashPattern([6, 5])
        painter.setPen(pen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(rect, 14, 14)

        cx, cy = self.width() // 2, 26
        wave_heights = [6, 12, 18, 10, 22, 14, 8, 16, 20, 11, 7]
        bar_w = 2.5
        spacing = 4
        total_w = len(wave_heights) * (bar_w + spacing) - spacing
        start_x = cx - total_w / 2

        painter.setPen(Qt.NoPen)
        accent = QColor(Theme.get_token("ACCENT_EMERALD", mode))
        for i, h in enumerate(wave_heights):
            x = start_x + i * (bar_w + spacing)
            painter.setBrush(accent)
            painter.drawRoundedRect(QRectF(x, cy - h / 2, bar_w, h), 1.2, 1.2)
