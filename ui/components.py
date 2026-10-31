import os
from PySide6.QtWidgets import QWidget, QPushButton, QHBoxLayout, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QFont, QColor, QLinearGradient, QPixmap,
    QPainter, QPainterPath, QPen
)

from .theme import (
    ACCENT_EMERALD, ACCENT_TEAL, ACCENT_RED, TEXT_FAINT,
    get_asset_path
)


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


# ─── Vector Alert Badge (For Dialog Modals) ───────────────────────────────────

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


# ─── Sidebar Native Logo ──────────────────────────────────────────────────────

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


# ─── Sidebar Rail Navigation Button ───────────────────────────────────────────

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


# ─── Group Header Widget (ClickUp Category Pills) ─────────────────────────────

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
