"""
Centralized theme color palette for dynamic widget styling.
"""
from core import database


_PALETTES = {
    "dark": {
        "bg": "#2b2b2b",
        "base": "#1e1e1e",
        "text": "#eeeeee",
        "border": "#555555",
        "card_bg": "#2a2a2a",
        "hover": "#3a3a3a",
        "selected": "#3a5a8a",
        "accent": "#64b5f6",
        "success": "#4caf50",
        "warning": "#ff9800",
        "danger": "#f44336",
        "muted": "#888888",
        "btn_bg": "#3a3a3a",
        "btn_hover": "#4a4a4a",
        "import_bg": "#3a5a8a",
        "import_hover": "#4a6aaa",
        "code_bg": "#444444",
        "tile_none": "#4a4a4a",
        "tile_good": "#2e7d32",
        "tile_mid":  "#f57f17",
        "tile_bad":  "#c62828",
        "tile_text": "#ffffff",
    },
    "light": {
        "bg": "#f5f5f5",
        "base": "#ffffff",
        "text": "#222222",
        "border": "#cccccc",
        "card_bg": "#ffffff",
        "hover": "#e0e0e0",
        "selected": "#a0c4ff",
        "accent": "#1976d2",
        "success": "#388e3c",
        "warning": "#f57c00",
        "danger": "#d32f2f",
        "muted": "#666666",
        "btn_bg": "#e0e0e0",
        "btn_hover": "#d0d0d0",
        "import_bg": "#5a8a5a",
        "import_hover": "#6a9a6a",
        "code_bg": "#eeeeee",
        "tile_none": "#e0e0e0",
        "tile_good": "#a5d6a7",
        "tile_mid":  "#fff59d",
        "tile_bad":  "#ef9a9a",
        "tile_text": "#222222",
    },
    "nature": {
        "bg": "#f4f7f2",
        "base": "#ffffff",
        "text": "#2f3e2f",
        "border": "#b8d0b0",
        "card_bg": "#ffffff",
        "hover": "#d4e4cc",
        "selected": "#8fb880",
        "accent": "#5a8f4b",
        "success": "#4a7f3b",
        "warning": "#c9a000",
        "danger": "#c05050",
        "muted": "#668866",
        "btn_bg": "#d4e4cc",
        "btn_hover": "#c4d8bc",
        "import_bg": "#5a8f4b",
        "import_hover": "#6a9f5b",
        "code_bg": "#e8f0e4",
        "tile_none": "#dcedc8",
        "tile_good": "#81c784",
        "tile_mid":  "#fff176",
        "tile_bad":  "#e57373",
        "tile_text": "#2f3e2f",
    },
}


def get_theme_colors(theme_name: str = None) -> dict:
    """Return the color palette dict for the given or current theme."""
    if theme_name is None:
        theme_name = database.get_setting("theme", "dark")
    return _PALETTES.get(theme_name, _PALETTES["dark"])
