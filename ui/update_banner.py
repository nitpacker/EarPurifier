"""
EarPurifier - Studio Update Banner.
Non-modal, elevated card widget anchored at the top of the workspace canvas.
Displays update notification, localized changelog preview, and direct download action.
"""

import logging
from typing import Any, Union, Dict
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy, QScrollArea
)
from PySide6.QtCore import Qt, QUrl, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QPen, QColor, QPainterPath, QLinearGradient, QDesktopServices, QCursor
)

from .theme import Theme, ThemeMode, get_primary_button_qss, get_scrollbar_qss

try:
    from i18n import t, is_rtl, get_current_language
except ImportError:
    from src.i18n import t, is_rtl, get_current_language

try:
    from update_checker import extract_release_notes
except ImportError:
    from src.update_checker import extract_release_notes

logger = logging.getLogger(__name__)


class VectorSparkleIcon(QWidget):
    """Crisp vector sparkle / star badge with Sprout-Teal gradient tint."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        mode = Theme.get_mode()
        c_emerald = QColor(Theme.get_token("ACCENT_EMERALD", mode))
        c_teal = QColor(Theme.get_token("ACCENT_TEAL", mode))

        # Soft glowing circular container
        bg_color = QColor(c_emerald)
        bg_color.setAlpha(36 if mode == ThemeMode.LIGHT else 45)
        painter.setBrush(bg_color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 8, 8)

        # Draw 4-point star / sparkle
        cx, cy = w / 2, h / 2
        path = QPainterPath()
        r_outer = 8.5
        r_inner = 2.8

        path.moveTo(cx, cy - r_outer)
        path.quadTo(cx, cy, cx + r_inner, cy)
        path.lineTo(cx + r_outer, cy)
        path.quadTo(cx, cy, cx, cy + r_inner)
        path.lineTo(cx, cy + r_outer)
        path.quadTo(cx, cy, cx - r_inner, cy)
        path.lineTo(cx - r_outer, cy)
        path.quadTo(cx, cy, cx, cy - r_inner)
        path.closeSubpath()

        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0, c_emerald)
        grad.setColorAt(1, c_teal)

        painter.setBrush(grad)
        painter.setPen(Qt.NoPen)
        painter.drawPath(path)

        # Secondary miniature accent sparkle
        p2 = QPainterPath()
        sx, sy = cx + 6.5, cy - 6.5
        s_out = 3.0
        s_in = 1.0
        p2.moveTo(sx, sy - s_out)
        p2.quadTo(sx, sy, sx + s_in, sy)
        p2.lineTo(sx + s_out, sy)
        p2.quadTo(sx, sy, sx, sy + s_in)
        p2.lineTo(sx, sy + s_out)
        p2.quadTo(sx, sy, sx - s_in, sy)
        p2.lineTo(sx - s_out, sy)
        p2.quadTo(sx, sy, sx, sy - s_in)
        p2.closeSubpath()
        painter.drawPath(p2)


class BannerCloseButton(QWidget):
    """Subtle circular dismiss button."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 22)
        self.setCursor(Qt.PointingHandCursor)
        self._hovered = False
        self.clicked = None

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and callable(self.clicked):
            self.clicked()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        mode = Theme.get_mode()
        if self._hovered:
            painter.setBrush(QColor(Theme.get_token("CARD_BORDER", mode)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 4, 4)

        pen_color = QColor(Theme.get_token("TEXT_BODY" if self._hovered else "TEXT_FAINT", mode))
        painter.setPen(QPen(pen_color, 1.6, Qt.SolidLine, Qt.RoundCap))

        cx, cy = self.width() // 2, self.height() // 2
        d = 3.5
        painter.drawLine(cx - d, cy - d, cx + d, cy + d)
        painter.drawLine(cx + d, cy - d, cx - d, cy + d)


class UpdateBannerWidget(QFrame):
    """
    Elevated Studio card anchored at the top of the queue canvas.
    Displays available update version, notes, download button, and remind-later action.
    """
    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.setObjectName("updateBannerCard")

        self.latest_version = ""
        self.raw_release_notes = ""
        self.html_url = ""
        self.download_url = ""

        self._theme_mode = Theme.get_mode()
        self._lang = self.config.get("language", "ar") if self.config else "ar"

        self.init_ui()
        self.apply_theme(self._theme_mode)

    def init_ui(self):
        direction = Qt.RightToLeft if is_rtl(self._lang) else Qt.LeftToRight
        self.setLayoutDirection(direction)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 10, 14, 10)
        main_layout.setSpacing(6)

        # Top Bar: Icon + Title + Version + Close
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.icon_badge = VectorSparkleIcon()
        top_bar.addWidget(self.icon_badge, 0, Qt.AlignVCenter)

        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet("font-size: 13px; font-weight: 800;")
        top_bar.addWidget(self.lbl_title, 1, Qt.AlignVCenter)

        self.btn_close = BannerCloseButton()
        self.btn_close.clicked = self.on_dismiss
        top_bar.addWidget(self.btn_close, 0, Qt.AlignVCenter)
        main_layout.addLayout(top_bar)

        # Body: Changelog preview inside sleek scroll area
        self.scroll_notes = QScrollArea()
        self.scroll_notes.setWidgetResizable(True)
        self.scroll_notes.setMaximumHeight(90)
        self.scroll_notes.setFrameShape(QFrame.NoFrame)
        self.scroll_notes.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.lbl_notes = QLabel()
        self.lbl_notes.setWordWrap(True)
        self.lbl_notes.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.scroll_notes.setWidget(self.lbl_notes)
        main_layout.addWidget(self.scroll_notes)

        # Bottom Bar: Actions
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(8)

        self.btn_download = QPushButton(t("btn_download_update"))
        self.btn_download.setCursor(Qt.PointingHandCursor)
        self.btn_download.clicked.connect(self.on_download)
        btn_bar.addWidget(self.btn_download)

        self.btn_remind = QPushButton(t("btn_dismiss_update"))
        self.btn_remind.setCursor(Qt.PointingHandCursor)
        self.btn_remind.clicked.connect(self.on_dismiss)
        btn_bar.addWidget(self.btn_remind)

        btn_bar.addStretch()
        main_layout.addLayout(btn_bar)

    def show_update(self, version: str, notes: Any, html_url: str, download_url: str):
        """Populates update details and smoothly reveals the banner."""
        self.latest_version = version
        self.raw_release_notes = notes
        self.html_url = html_url
        self.download_url = download_url or html_url

        self.retranslate_ui(self._lang)
        self.setVisible(True)

    def on_download(self):
        url_to_open = self.download_url or self.html_url
        if url_to_open:
            QDesktopServices.openUrl(QUrl(url_to_open))
        self.setVisible(False)

    def on_dismiss(self):
        """Hides banner for the current application session."""
        self.setVisible(False)

    def retranslate_ui(self, lang: str = "ar"):
        self._lang = lang
        direction = Qt.RightToLeft if is_rtl(lang) else Qt.LeftToRight
        self.setLayoutDirection(direction)

        if self.latest_version:
            self.lbl_title.setText(t("update_banner_title", version=self.latest_version))
            extracted = extract_release_notes(self.raw_release_notes, lang)
            self.lbl_notes.setText(extracted if extracted else t("update_banner_desc", version=self.latest_version))
        else:
            self.lbl_title.setText(t("update_banner_title", version=""))
            self.lbl_notes.setText(t("update_banner_desc", version=""))

        self.btn_download.setText(t("btn_download_update"))
        self.btn_remind.setText(t("btn_dismiss_update"))

    def apply_theme(self, mode: str):
        self._theme_mode = mode
        card_bg = Theme.get_token("CARD_BG", mode)
        card_border = Theme.get_token("CARD_BORDER", mode)
        text_head = Theme.get_token("TEXT_HEAD", mode)
        text_muted = Theme.get_token("TEXT_MUTED", mode)
        meta_bg = Theme.get_token("META_BG", mode)

        self.setStyleSheet(f"""
            QFrame#updateBannerCard {{
                background-color: {card_bg};
                border: 1px solid {card_border};
                border-radius: 10px;
                margin: 6px 12px 2px 12px;
            }}
            QLabel {{
                background: transparent;
            }}
        """)

        if hasattr(self, 'scroll_notes'):
            self.scroll_notes.setStyleSheet(get_scrollbar_qss(mode) + "background: transparent; border: none;")

        self.lbl_title.setStyleSheet(f"font-size: 13px; font-weight: 800; color: {text_head};")
        self.lbl_notes.setStyleSheet(f"font-size: 11.5px; line-height: 1.4; color: {text_muted};")

        self.btn_download.setStyleSheet(get_primary_button_qss(mode))
        sec_btn_qss = f"""
            QPushButton {{
                background-color: {meta_bg};
                color: {text_muted};
                border: 1px solid {card_border};
                border-radius: 8px;
                padding: 7px 14px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                color: {text_head};
                border-color: {Theme.get_token('ACCENT_EMERALD', mode)};
            }}
        """
        self.btn_remind.setStyleSheet(sec_btn_qss)

        self.icon_badge.update()
        self.btn_close.update()
