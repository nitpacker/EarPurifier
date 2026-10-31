import os
import sys

# ─── Design Tokens & Theme Namespace ──────────────────────────────────────────

class Theme:
    """
    Centralized design tokens for EarPurifier desktop application.
    Matches the Sprout & Wave serene botanical theme.
    """
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

    # Typography Font Family
    FONT_FAMILY = "'Segoe UI', -apple-system, BlinkMacSystemFont, 'Inter', Roboto, sans-serif"


# ─── Dual Token Exports (Module-Level Constants for Ergonomics & Safety) ──────
SIDEBAR_BG = Theme.SIDEBAR_BG
SIDEBAR_BORDER = Theme.SIDEBAR_BORDER
SIDEBAR_ITEM_HOVER = Theme.SIDEBAR_ITEM_HOVER
SIDEBAR_ITEM_ACTIVE = Theme.SIDEBAR_ITEM_ACTIVE
SIDEBAR_ACCENT = Theme.SIDEBAR_ACCENT

CANVAS_BG = Theme.CANVAS_BG
CARD_BG = Theme.CARD_BG
CARD_BORDER = Theme.CARD_BORDER
CARD_BORDER_HOVER = Theme.CARD_BORDER_HOVER

TEXT_HEAD = Theme.TEXT_HEAD
TEXT_BODY = Theme.TEXT_BODY
TEXT_MUTED = Theme.TEXT_MUTED
TEXT_FAINT = Theme.TEXT_FAINT

ACCENT_EMERALD = Theme.ACCENT_EMERALD
ACCENT_MINT = Theme.ACCENT_MINT
ACCENT_TEAL = Theme.ACCENT_TEAL
ACCENT_CYAN = Theme.ACCENT_CYAN
ACCENT_BLUE = Theme.ACCENT_BLUE
ACCENT_AMBER = Theme.ACCENT_AMBER
ACCENT_RED = Theme.ACCENT_RED

FONT_FAMILY = Theme.FONT_FAMILY


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
        # Resolves cleanerEARS/assets from cleanerEARS/ui/
        base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    return os.path.join(base_dir, filename)


# ─── Common QSS Templates ─────────────────────────────────────────────────────
def get_scrollbar_qss() -> str:
    """Returns standard sleek scrollbar styling for list and queue containers."""
    return f"""
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
    """


def get_combobox_qss() -> str:
    """Returns modern non-beveled combobox styling with clean rounded popup."""
    return f"""
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
    """


def get_primary_button_qss() -> str:
    """Returns primary action button with Sprout-Teal vibrant gradient."""
    return f"""
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
    """
