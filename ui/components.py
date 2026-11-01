import os
import math
from PySide6.QtWidgets import (
    QWidget, QPushButton, QHBoxLayout, QVBoxLayout, QLabel
)
from PySide6.QtCore import Qt, Signal, QTimer, QRectF
from PySide6.QtGui import (
    QFont, QColor, QLinearGradient, QPixmap,
    QPainter, QPainterPath, QPen, QBrush
)

from .theme import (
    Theme, ThemeMode, get_asset_path,
    FONT_FAMILY
)
from .queue_widgets import (
    SegmentedPillSwitcher, FloatingBatchDock, DropZoneWidget
)

try:
    from i18n import t, is_rtl
except ImportError:
    from src.i18n import t, is_rtl

try:
    from update_checker import APP_VERSION
except ImportError:
    from src.update_checker import APP_VERSION


# ─── 1. Clean '✕' Mark Button ──────────────────────────────────────────────────

class CleanCloseButton(QPushButton):
    """Sleek minimalist circular '✕' button for removing jobs from history."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(t("btn_remove_tooltip"))
        self._hovered = False

    def retranslate_ui(self, tooltip: str = ""):
        self.setToolTip(tooltip or t("btn_remove_tooltip"))

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
            painter.setBrush(QColor(239, 68, 68, 26))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))

        mode = Theme.get_mode()
        color = QColor(Theme.get_token("ACCENT_RED", mode)) if self._hovered else QColor(Theme.get_token("TEXT_FAINT", mode))
        pen = QPen(color, 1.6, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)

        cx, cy = self.width() // 2, self.height() // 2
        d = 4
        painter.drawLine(cx - d, cy - d, cx + d, cy + d)
        painter.drawLine(cx + d, cy - d, cx - d, cy + d)


# ─── 2. Vector Alert Badge ────────────────────────────────────────────────────

class VectorAlertBadge(QWidget):
    """Circular alert badge with a clean '✕' mark for confirmation dialogs."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 44)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setBrush(QColor(239, 68, 68, 20))
        painter.setPen(QPen(QColor(239, 68, 68, 60), 1))
        painter.drawEllipse(self.rect().adjusted(2, 2, -2, -2))

        pen = QPen(QColor("#ef4444"), 2.2, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)
        cx, cy = self.width() // 2, self.height() // 2
        d = 6
        painter.drawLine(cx - d, cy - d, cx + d, cy + d)
        painter.drawLine(cx + d, cy - d, cx - d, cy + d)


# ─── 3. Sidebar Native Logo with Version Pill ─────────────────────────────────

class SidebarLogo(QWidget):
    """Sprout & Wave native logo with integrated v2.0 version badge."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(54, 58)
        self.logo_path = get_asset_path("logo.png")
        self.pixmap = None
        if os.path.exists(self.logo_path):
            self.pixmap = QPixmap(self.logo_path)
        self.setToolTip(t("logo_tooltip"))

    def retranslate_ui(self, tooltip: str = ""):
        self.setToolTip(tooltip or t("logo_tooltip"))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # 1. Logo Icon (38x38)
        logo_rect = QRectF((self.width() - 38) / 2, 2, 38, 38)
        if self.pixmap and not self.pixmap.isNull():
            painter.drawPixmap(logo_rect.toRect(), self.pixmap)
        else:
            grad = QLinearGradient(logo_rect.topLeft(), logo_rect.bottomRight())
            grad.setColorAt(0, QColor("#10b981"))
            grad.setColorAt(1, QColor("#0d9488"))
            painter.setBrush(grad)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(logo_rect, 8, 8)

        # 2. Dynamic Version Pill (e.g. "v0.0.1")
        font = QFont("Consolas", 8, QFont.Bold)
        painter.setFont(font)
        ver_text = f"v{APP_VERSION}"
        text_w = painter.fontMetrics().horizontalAdvance(ver_text)
        pill_w = max(36, text_w + 8)
        pill_rect = QRectF((self.width() - pill_w) / 2, 44, pill_w, 13)

        painter.setBrush(QColor("#182e23"))
        painter.setPen(QPen(QColor("#244837"), 1))
        painter.drawRoundedRect(pill_rect, 4, 4)

        painter.setPen(QColor("#95daa3"))
        painter.drawText(pill_rect, Qt.AlignCenter, ver_text)


# ─── 4. Sidebar Rail Navigation Button ────────────────────────────────────────

class SidebarNavButton(QPushButton):
    """Studio rail navigation button with luminous vertical pill indicator."""
    def __init__(self, icon_type: str, label_text: str, parent=None):
        super().__init__(parent)
        self.icon_type = icon_type
        self.label_text = label_text
        self.is_active = False
        self._hovered = False
        self.setFixedHeight(54)
        self.setFixedWidth(58)
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
            painter.setBrush(QColor(16, 185, 129, 36))
            painter.setPen(QPen(QColor(16, 185, 129, 70), 1))
            painter.drawRoundedRect(rect, 8, 8)

            # Luminous vertical pill indicator (mirrored in RTL)
            painter.setBrush(QColor("#95daa3"))
            painter.setPen(Qt.NoPen)
            pill_x = self.width() - 3 if is_rtl() else 0
            painter.drawRoundedRect(pill_x, 12, 3, 30, 1.5, 1.5)
        elif self._hovered:
            painter.setBrush(QColor(255, 255, 255, 14))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 8, 8)

        color = QColor("#ffffff") if self.is_active else (QColor("#e2ede7") if self._hovered else QColor("#86a193"))
        pen = QPen(color, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        cx, cy = self.width() // 2, 18

        if self.icon_type == "cloud":
            cloud = QPainterPath()
            cloud.moveTo(cx - 7, cy + 4)
            cloud.lineTo(cx + 6, cy + 4)
            cloud.arcTo(cx + 3, cy - 1, 6, 5, 270, 180)
            cloud.arcTo(cx - 3, cy - 6, 8, 8, 0, 180)
            cloud.arcTo(cx - 9, cy - 2, 6, 6, 90, 180)
            cloud.closeSubpath()
            painter.drawPath(cloud)
        elif self.icon_type == "local":
            # Sleek desktop studio monitor on a pedestal stand
            painter.drawRoundedRect(cx - 8, cy - 8, 16, 11, 2, 2)
            painter.drawLine(cx, cy + 3, cx, cy + 6)
            painter.drawLine(cx - 4, cy + 6, cx + 4, cy + 6)
        elif self.icon_type == "settings":
            import math
            gear = QPainterPath()
            outer_r, inner_r, center_r, teeth = 6.8, 5.0, 2.3, 6
            for i in range(teeth):
                angle_deg = i * (360.0 / teeth)
                a1 = math.radians(angle_deg - 14)
                a2 = math.radians(angle_deg - 7)
                a3 = math.radians(angle_deg + 7)
                a4 = math.radians(angle_deg + 14)
                if i == 0:
                    gear.moveTo(cx + inner_r * math.cos(a1), cy + inner_r * math.sin(a1))
                else:
                    gear.lineTo(cx + inner_r * math.cos(a1), cy + inner_r * math.sin(a1))
                gear.lineTo(cx + outer_r * math.cos(a2), cy + outer_r * math.sin(a2))
                gear.lineTo(cx + outer_r * math.cos(a3), cy + outer_r * math.sin(a3))
                gear.lineTo(cx + inner_r * math.cos(a4), cy + inner_r * math.sin(a4))
            gear.closeSubpath()
            painter.drawPath(gear)
            painter.drawEllipse(QRectF(cx - center_r, cy - center_r, center_r * 2, center_r * 2))

        painter.setPen(color)
        font = QFont(FONT_FAMILY, 8, QFont.Bold if self.is_active else QFont.DemiBold)
        painter.setFont(font)
        painter.drawText(0, 34, self.width(), 16, Qt.AlignCenter, self.label_text)

    def retranslate_ui(self, label_text: str, tooltip: str = ""):
        self.label_text = label_text
        if tooltip:
            self.setToolTip(tooltip)
        self.update()


# ─── 5. Sidebar Theme Toggle Button ───────────────────────────────────────────

class SidebarThemeButton(QPushButton):
    """One-click Theme Toggle button (☀ Sun / 🌙 Moon) directly in the sidebar rail."""
    theme_toggled = Signal(str)

    def __init__(self, initial_mode: str = "light", parent=None):
        super().__init__(parent)
        self.theme_mode = initial_mode
        self.setFixedSize(40, 40)
        self.setCursor(Qt.PointingHandCursor)
        self._hovered = False
        self._update_tooltip()

    def set_theme_mode(self, mode: str):
        self.theme_mode = mode
        self._update_tooltip()
        self.update()

    def _update_tooltip(self):
        tip = t("theme_toggle_dark") if self.theme_mode == ThemeMode.LIGHT else t("theme_toggle_light")
        self.setToolTip(tip)

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)

            rect = self.rect().adjusted(2, 2, -2, -2)
            bg = QColor(255, 255, 255, 22) if self._hovered else QColor(20, 38, 28, 180)
            border = QColor("#223d2e") if not self._hovered else QColor("#34d399")

            painter.setBrush(bg)
            painter.setPen(QPen(border, 1))
            painter.drawRoundedRect(rect, 8, 8)

            cx, cy = self.width() // 2, self.height() // 2

            if self.theme_mode == ThemeMode.LIGHT:
                # Warm golden-amber crescent moon with rich fill
                amber_pen = QPen(QColor("#f59e0b"), 1.6, Qt.SolidLine, Qt.RoundCap)
                painter.setPen(amber_pen)
                painter.setBrush(QBrush(QColor(245, 158, 11, 215)))
                moon = QPainterPath()
                moon.moveTo(cx + 3, cy - 6)
                moon.cubicTo(cx - 5, cy - 5, cx - 5, cy + 5, cx + 3, cy + 6)
                moon.cubicTo(cx - 1, cy + 3.5, cx - 1, cy - 3.5, cx + 3, cy - 6)
                painter.drawPath(moon)
            else:
                # Radiant golden sun
                sun_pen = QPen(QColor("#fbbf24"), 1.8, Qt.SolidLine, Qt.RoundCap)
                painter.setPen(sun_pen)
                painter.setBrush(QBrush(QColor(251, 191, 36, 230)))
                painter.drawEllipse(cx - 3, cy - 3, 6, 6)
                painter.setBrush(Qt.NoBrush)
                for dx, dy in [(0, -7), (0, 7), (-7, 0), (7, 0), (-5, -5), (5, 5), (-5, 5), (5, -5)]:
                    painter.drawLine(cx + int(dx * 0.65), cy + int(dy * 0.65), cx + dx, cy + dy)
        except Exception:
            pass


# ─── 6. Serene Engine Telemetry Pill ──────────────────────────────────────────

class EngineTelemetryPill(QWidget):
    """
    Engine telemetry capsule at the bottom of the navigation rail.
    Completely STATIC when idle/ready (NO strobe/flashing).
    Subtle 3-second breathing cycle only when actively processing.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(58, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.is_active = False
        self._breath_phase = 0.0
        self.setToolTip(t("engine_ready_tooltip"))

        self.breath_timer = QTimer(self)
        self.breath_timer.setInterval(60)
        self.breath_timer.timeout.connect(self._on_breath_tick)

    def set_active_processing(self, active: bool):
        if self.is_active == active:
            return
        self.is_active = active
        if active:
            self.breath_timer.start()
        else:
            self.breath_timer.stop()
            self._breath_phase = 0.0
        self.update()

    def _on_breath_tick(self):
        self._breath_phase = (self._breath_phase + (math.pi / 25.0)) % (2 * math.pi)
        self.update()

    def retranslate_ui(self):
        self.setToolTip(t("engine_ready_tooltip"))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setBrush(QColor(18, 28, 22))
        painter.setPen(QPen(QColor(30, 51, 40), 1))
        painter.drawRoundedRect(rect, 11, 11)

        dot_alpha = int(255 * (0.675 + 0.325 * math.sin(self._breath_phase))) if self.is_active else 255
        dot_color = QColor(16, 185, 129, dot_alpha)

        dot_x = self.width() - 11 if is_rtl() else 7
        painter.setBrush(dot_color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(dot_x, 8, 7, 7)

        painter.setPen(QColor("#95daa3"))
        painter.setFont(QFont("Consolas", 8, QFont.Bold))
        text_label = t("engine_telemetry_active") if self.is_active else t("engine_telemetry_ready")
        text_x = 4 if is_rtl() else 18
        painter.drawText(text_x, 0, self.width() - 22, self.height(), Qt.AlignCenter, text_label)


# ─── 7. Modern iOS-Style Toggle Switch ───────────────────────────────────────

class ModernToggleSwitch(QWidget):
    """Custom-painted iOS-style toggle switch for settings dialogs."""
    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setFixedSize(38, 22)
        self.setCursor(Qt.PointingHandCursor)
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if self._checked != checked:
            self._checked = checked
            self.update()
            self.toggled.emit(checked)

    def mousePressEvent(self, event):
        self.setChecked(not self._checked)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)
        mode = Theme.get_mode()
        accent = QColor(Theme.get_token("ACCENT_EMERALD", mode))
        inactive = QColor("#cbd5e1") if mode == ThemeMode.LIGHT else QColor("#334155")

        painter.setBrush(accent if self._checked else inactive)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, 10, 10)

        thumb_x = (rect.right() - 17) if self._checked else (rect.left() + 2)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(thumb_x, rect.top() + 2, 16, 16))


# ─── 8. Status Group Header (ClickUp Style) ──────────────────────────────────

class StatusGroupHeader(QWidget):
    def __init__(self, title: str, count: int, color_hex: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 10, 6, 4)
        layout.setSpacing(6)

        lbl_pill = QLabel(f" {title.upper()}  {count} ")
        lbl_pill.setStyleSheet(f"""
            background-color: {color_hex};
            color: #ffffff;
            font-size: 10px;
            font-weight: 800;
            padding: 2px 8px;
            border-radius: 9px;
            letter-spacing: 0.5px;
        """)
        layout.addWidget(lbl_pill)
        layout.addStretch()


# ─── 9. Vector Rotating Arrows Spinner ────────────────────────────────────────

class RotatingSpinner(QWidget):
    """
    Antialiased smooth rotating dual-arc spinner for active/processing jobs.
    Stops timer and hides when inactive to maintain zero idle CPU overhead.
    """
    def __init__(self, size: int = 14, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._is_spinning = False
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._rotate)
        self.hide()

    def start(self):
        if not self._is_spinning:
            self._is_spinning = True
            self._timer.start()
            self.show()
            self.update()

    def stop(self):
        if self._is_spinning:
            self._is_spinning = False
            self._timer.stop()
            self.hide()

    def _rotate(self):
        self._angle = (self._angle + 18) % 360
        self.update()

    def paintEvent(self, event):
        if not self._is_spinning:
            return
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)

            cx = self.width() / 2.0
            cy = self.height() / 2.0
            r = (min(self.width(), self.height()) - 3) / 2.0

            painter.translate(cx, cy)
            painter.rotate(self._angle)

            mode = Theme.get_mode()
            color = QColor(Theme.get_token("ACCENT_EMERALD", mode))
            pen = QPen(color, 2.0, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)

            rect = QRectF(-r, -r, r * 2, r * 2)
            # Draw two elegant arcs (120 degrees each)
            painter.drawArc(rect, 0 * 16, 120 * 16)
            painter.drawArc(rect, 180 * 16, 120 * 16)
        except Exception:
            pass

