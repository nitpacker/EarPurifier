import os
import sys
from typing import Dict, Any

# ─── Design Tokens & Theme Namespace ──────────────────────────────────────────

class ThemeMode:
    LIGHT = "light"
    DARK = "dark"


class Theme:
    """
    Centralized design tokens for EarPurifier desktop application.
    Supports dual Light (Soft Sage - Default) and Dark (Deep Botanical Slate) themes.
    """
    _current_mode = ThemeMode.LIGHT

    # Palette definition for both themes
    PALETTES: Dict[str, Dict[str, str]] = {
        ThemeMode.LIGHT: {
            "CANVAS_BG": "#f4f8f5",
            "CARD_BG": "#ffffff",
            "CARD_BORDER": "#dfebe4",
            "CARD_BORDER_HOVER": "#bad4c7",
            "META_BG": "#f8faf8",
            "SIDEBAR_BG": "#0d1a14",
            "SIDEBAR_BORDER": "#182e23",
            "SIDEBAR_ITEM_HOVER": "rgba(16, 185, 129, 0.08)",
            "SIDEBAR_ITEM_ACTIVE": "rgba(16, 185, 129, 0.18)",
            "SIDEBAR_ACCENT": "#10b981",
            "TEXT_HEAD": "#0b2318",
            "TEXT_BODY": "#233d30",
            "TEXT_MUTED": "#557364",
            "TEXT_FAINT": "#86a193",
            "ACCENT_EMERALD": "#10b981",
            "ACCENT_MINT": "#34d399",
            "ACCENT_TEAL": "#0d9488",
            "ACCENT_CYAN": "#06b6d4",
            "ACCENT_BLUE": "#0284c7",
            "ACCENT_AMBER": "#f59e0b",
            "ACCENT_RED": "#ef4444",
            "DOCK_BG": "rgba(255, 255, 255, 0.95)",
            "DOCK_BORDER": "#bad4c7",
        },
        ThemeMode.DARK: {
            "CANVAS_BG": "#0c1410",
            "CARD_BG": "#14211a",
            "CARD_BORDER": "#1e3328",
            "CARD_BORDER_HOVER": "#2b4939",
            "META_BG": "#0d1712",
            "SIDEBAR_BG": "#080d0a",
            "SIDEBAR_BORDER": "#14211a",
            "SIDEBAR_ITEM_HOVER": "rgba(149, 218, 163, 0.1)",
            "SIDEBAR_ITEM_ACTIVE": "rgba(149, 218, 163, 0.22)",
            "SIDEBAR_ACCENT": "#95daa3",
            "TEXT_HEAD": "#e8f3ec",
            "TEXT_BODY": "#c1d7cb",
            "TEXT_MUTED": "#749683",
            "TEXT_FAINT": "#445d50",
            "ACCENT_EMERALD": "#95daa3",
            "ACCENT_MINT": "#34d399",
            "ACCENT_TEAL": "#237f8a",
            "ACCENT_CYAN": "#38bdf8",
            "ACCENT_BLUE": "#38bdf8",
            "ACCENT_AMBER": "#fbbf24",
            "ACCENT_RED": "#f87171",
            "DOCK_BG": "rgba(20, 33, 26, 0.95)",
            "DOCK_BORDER": "#2b4939",
        }
    }

    @classmethod
    def resolve_font_family(cls, lang: str = "ar") -> str:
        """
        Detects and returns the single highest-quality font family installed on the OS.
        Guarantees exact font match, crisp DirectWrite hinting, and zero dotted/pixelated distortion.
        Anticipates machines without custom fonts: falls back gracefully through standard OS fonts.
        """
        try:
            from PySide6.QtGui import QGuiApplication, QFontDatabase
            if not QGuiApplication.instance():
                return "Dubai" if lang == "ar" else "Plus Jakarta Sans"
            installed = set(QFontDatabase.families())
        except Exception:
            return "Segoe UI"

        if lang == "ar":
            for font in ["Cairo", "Dubai", "Segoe UI Variable Text", "Segoe UI", "Tahoma"]:
                if font in installed:
                    return font
            return "Segoe UI"
        else:
            for font in ["Plus Jakarta Sans", "Segoe UI Variable Display", "Segoe UI", "Arial"]:
                if font in installed:
                    return font
            return "Segoe UI"

    @classmethod
    def resolve_mono_font(cls) -> str:
        """
        Detects and returns the single highest-quality monospaced font installed on the OS.
        Priority: JetBrains Mono -> Consolas -> Courier New
        """
        try:
            from PySide6.QtGui import QGuiApplication, QFontDatabase
            if not QGuiApplication.instance():
                return "Consolas"
            installed = set(QFontDatabase.families())
        except Exception:
            return "Consolas"

        for font in ["JetBrains Mono", "Consolas", "Courier New"]:
            if font in installed:
                return font
        return "Consolas"

    FONT_FAMILY_AR = "Dubai"
    FONT_FAMILY_EN = "Plus Jakarta Sans"
    FONT_FAMILY = "Dubai"
    FONT_MONO = "Consolas"

    @classmethod
    def set_mode(cls, mode: str):
        if mode in [ThemeMode.LIGHT, ThemeMode.DARK]:
            cls._current_mode = mode

    @classmethod
    def get_mode(cls) -> str:
        return cls._current_mode

    @classmethod
    def get_token(cls, token_name: str, mode: str = None) -> str:
        target_mode = mode or cls._current_mode
        palette = cls.PALETTES.get(target_mode, cls.PALETTES[ThemeMode.LIGHT])
        return palette.get(token_name, "")


# ─── Module-Level Accessor Properties ─────────────────────────────────────────

def get_current_mode() -> str:
    return Theme.get_mode()

def set_current_mode(mode: str):
    Theme.set_mode(mode)


# ─── Dual Token Exports (Defaults to Active Palette) ──────────────────────────
CANVAS_BG = Theme.PALETTES[ThemeMode.LIGHT]["CANVAS_BG"]
CARD_BG = Theme.PALETTES[ThemeMode.LIGHT]["CARD_BG"]
CARD_BORDER = Theme.PALETTES[ThemeMode.LIGHT]["CARD_BORDER"]
CARD_BORDER_HOVER = Theme.PALETTES[ThemeMode.LIGHT]["CARD_BORDER_HOVER"]
META_BG = Theme.PALETTES[ThemeMode.LIGHT]["META_BG"]

SIDEBAR_BG = Theme.PALETTES[ThemeMode.LIGHT]["SIDEBAR_BG"]
SIDEBAR_BORDER = Theme.PALETTES[ThemeMode.LIGHT]["SIDEBAR_BORDER"]
SIDEBAR_ITEM_HOVER = Theme.PALETTES[ThemeMode.LIGHT]["SIDEBAR_ITEM_HOVER"]
SIDEBAR_ITEM_ACTIVE = Theme.PALETTES[ThemeMode.LIGHT]["SIDEBAR_ITEM_ACTIVE"]
SIDEBAR_ACCENT = Theme.PALETTES[ThemeMode.LIGHT]["SIDEBAR_ACCENT"]

TEXT_HEAD = Theme.PALETTES[ThemeMode.LIGHT]["TEXT_HEAD"]
TEXT_BODY = Theme.PALETTES[ThemeMode.LIGHT]["TEXT_BODY"]
TEXT_MUTED = Theme.PALETTES[ThemeMode.LIGHT]["TEXT_MUTED"]
TEXT_FAINT = Theme.PALETTES[ThemeMode.LIGHT]["TEXT_FAINT"]

ACCENT_EMERALD = Theme.PALETTES[ThemeMode.LIGHT]["ACCENT_EMERALD"]
ACCENT_MINT = Theme.PALETTES[ThemeMode.LIGHT]["ACCENT_MINT"]
ACCENT_TEAL = Theme.PALETTES[ThemeMode.LIGHT]["ACCENT_TEAL"]
ACCENT_CYAN = Theme.PALETTES[ThemeMode.LIGHT]["ACCENT_CYAN"]
ACCENT_BLUE = Theme.PALETTES[ThemeMode.LIGHT]["ACCENT_BLUE"]
ACCENT_AMBER = Theme.PALETTES[ThemeMode.LIGHT]["ACCENT_AMBER"]
ACCENT_RED = Theme.PALETTES[ThemeMode.LIGHT]["ACCENT_RED"]

resolve_font_family = Theme.resolve_font_family
resolve_mono_font = Theme.resolve_mono_font
get_font_family = Theme.resolve_font_family

FONT_FAMILY_AR = resolve_font_family("ar")
FONT_FAMILY_EN = resolve_font_family("en")
FONT_FAMILY = FONT_FAMILY_AR
FONT_MONO = resolve_mono_font()


# ─── Supported Media Extensions ───────────────────────────────────────────────
SUPPORTED_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
    ".weba", ".m4a", ".m4b", ".mka",
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".opus",
}


# ─── Asset Helper ─────────────────────────────────────────────────────────────
def get_asset_path(filename: str) -> str:
    """Get absolute path to asset file, works for dev and PyInstaller onefile."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_dir = os.path.join(sys._MEIPASS, "src", "assets")
        if not os.path.exists(base_dir):
            base_dir = os.path.join(sys._MEIPASS, "assets")
    else:
        base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    return os.path.join(base_dir, filename)


# ─── Common QSS Templates ─────────────────────────────────────────────────────

def get_checkbox_qss(theme_mode: str = None, accent_color: str = None) -> str:
    """
    Returns modern Linear/Figma checkbox styling with an embedded crisp white SVG checkmark.
    Fixes flat solid block bug when checked.
    """
    mode = theme_mode or Theme.get_mode()
    border = Theme.get_token("CARD_BORDER", mode)
    meta_bg = Theme.get_token("META_BG", mode)
    accent = accent_color or Theme.get_token("ACCENT_EMERALD", mode)
    check_svg = get_asset_path("check_white.svg").replace("\\", "/")

    return f"""
        QCheckBox {{
            spacing: 8px;
            background: transparent;
            font-size: 12px;
            font-weight: 600;
            border: none;
            outline: none;
        }}
        QCheckBox::indicator {{
            width: 17px;
            height: 17px;
            border: 1.5px solid {border};
            border-radius: 4px;
            background-color: {meta_bg};
        }}
        QCheckBox::indicator:hover {{
            border-color: {accent};
        }}
        QCheckBox::indicator:checked {{
            background-color: {accent};
            border: 1.5px solid {accent};
            image: url({check_svg});
        }}
        QCheckBox::indicator:disabled {{
            background-color: {border};
            border-color: {border};
        }}
    """


def get_scrollbar_qss(theme_mode: str = None) -> str:
    """Returns sleek 6px scrollbar styling for list and queue containers."""
    mode = theme_mode or Theme.get_mode()
    track_bg = "transparent"
    thumb_bg = Theme.get_token("CARD_BORDER", mode)
    thumb_hover = Theme.get_token("TEXT_FAINT", mode)

    return f"""
        QScrollBar:vertical {{
            background: {track_bg};
            width: 6px;
            border-radius: 3px;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: {thumb_bg};
            border-radius: 3px;
            min-height: 28px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {thumb_hover};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
            background: none;
            border: none;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
        }}
    """


def get_combobox_qss(is_rtl: bool = False, theme_mode: str = None) -> str:
    """Returns modern non-beveled combobox styling with vector down-arrow."""
    mode = theme_mode or Theme.get_mode()
    card_bg = Theme.get_token("CARD_BG", mode)
    card_border = Theme.get_token("CARD_BORDER", mode)
    text_head = Theme.get_token("TEXT_HEAD", mode)
    accent = Theme.get_token("ACCENT_EMERALD", mode)

    padding_val = "6px 12px 6px 28px" if is_rtl else "6px 28px 6px 12px"
    subcontrol_pos = "top left" if is_rtl else "top right"
    arrow_margin = "margin-left: 8px;" if is_rtl else "margin-right: 8px;"
    item_padding = "padding-right: 8px;" if is_rtl else "padding-left: 8px;"
    selection_bg = "rgba(16, 185, 129, 0.12)" if mode == ThemeMode.LIGHT else "rgba(149, 218, 163, 0.15)"

    arrow_file = "arrow_down_dark.svg" if mode == ThemeMode.DARK else "arrow_down.svg"
    arrow_path = get_asset_path(arrow_file).replace("\\", "/")

    return f"""
        QComboBox {{
            background-color: {card_bg};
            border: 1px solid {card_border};
            border-radius: 7px;
            padding: {padding_val};
            color: {text_head};
            font-weight: 600;
            font-size: 12px;
            min-width: 130px;
        }}
        QComboBox:hover {{
            border-color: {accent};
            background-color: {card_bg};
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: {subcontrol_pos};
            width: 24px;
            border: none;
            background: transparent;
        }}
        QComboBox::down-arrow {{
            image: url("{arrow_path}");
            width: 10px;
            height: 10px;
            {arrow_margin}
        }}
        QComboBox QAbstractItemView {{
            background-color: {card_bg};
            border: 1px solid {card_border};
            border-radius: 8px;
            selection-background-color: {selection_bg};
            selection-color: {accent};
            color: {text_head};
            padding: 4px;
            outline: 0px;
        }}
        QComboBox QAbstractItemView::item {{
            height: 28px;
            {item_padding}
            border-radius: 4px;
        }}
    """


def get_sidebar_qss(is_rtl: bool = False, theme_mode: str = None) -> str:
    """Returns dynamic border styling for the navigation rail."""
    mode = theme_mode or Theme.get_mode()
    sidebar_bg = Theme.get_token("SIDEBAR_BG", mode)
    sidebar_border = Theme.get_token("SIDEBAR_BORDER", mode)
    border_side = "left" if is_rtl else "right"
    other_side = "right" if is_rtl else "left"

    return f"""
        QWidget#navigationRail {{
            background-color: {sidebar_bg};
            border-{border_side}: 1px solid {sidebar_border};
            border-{other_side}: none;
        }}
    """


def get_primary_button_qss(theme_mode: str = None) -> str:
    """Returns primary action button with Sprout-Teal vibrant gradient."""
    mode = theme_mode or Theme.get_mode()
    c1 = Theme.get_token("ACCENT_EMERALD", mode)
    c2 = Theme.get_token("ACCENT_TEAL", mode)
    hover_c1 = Theme.get_token("ACCENT_MINT", mode)

    return f"""
        QPushButton {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {c1}, stop:1 {c2});
            color: #ffffff;
            font-weight: 800;
            font-size: 12.5px;
            padding: 8px 18px;
            border-radius: 8px;
            border: none;
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {hover_c1}, stop:1 {c2});
        }}
        QPushButton:pressed {{
            background: {c2};
        }}
        QPushButton:disabled {{
            background: #a7d0be;
            color: #ffffff;
        }}
    """


_cached_yellow_folder_icon = None

def get_yellow_folder_icon():
    """Returns a crisp vector QIcon of a golden-yellow folder for 'Show in Folder' button."""
    global _cached_yellow_folder_icon
    if _cached_yellow_folder_icon is None:
        try:
            from PySide6.QtGui import QIcon, QPixmap, QPainter
            from PySide6.QtCore import Qt, QByteArray
            from PySide6.QtSvg import QSvgRenderer

            svg_text = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
  <path fill="#f59e0b" d="M20 6h-8l-2-2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2z"/>
  <path fill="#fbbf24" d="M20 8H4v10c0 .55.45 1 1 1h14c.55 0 1-.45 1-1V8z"/>
</svg>"""
            renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
            pix = QPixmap(32, 32)
            pix.fill(Qt.transparent)
            painter = QPainter(pix)
            renderer.render(painter)
            painter.end()
            _cached_yellow_folder_icon = QIcon(pix)
        except Exception:
            _cached_yellow_folder_icon = None
    return _cached_yellow_folder_icon
