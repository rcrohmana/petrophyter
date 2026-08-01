"""
Centralized color definitions for Petrophyter themes.
All colors should be accessed through get_color() or get_plot_color() functions.

This ensures consistent theming across the application and makes it easy
to maintain and update color schemes.
"""

import logging
from typing import Dict, Optional


logger = logging.getLogger(__name__)

# =============================================================================
# SEMANTIC COLOR DEFINITIONS
# =============================================================================

LIGHT_COLORS: Dict[str, str] = {
    # Backgrounds
    "bg_primary": "#E8E3D9",  # Main window background
    "bg_surface": "#F0EBE1",  # Cards, inputs, tables
    "bg_surface_alt": "#E0DBD1",  # Alternate surface (buttons, headers)
    "bg_surface_hover": "#E5DFD4",
    "bg_surface_pressed": "#D5CFC4",
    # Text
    "text_primary": "#000000",
    "text_secondary": "#4A4540",
    "text_tertiary": "#666666",
    "text_disabled": "#999999",
    "text_placeholder": "#555555",
    # Borders
    "border": "#C9C0B0",
    "border_light": "#D5CFC4",
    # Accent/Brand colors
    "primary": "#1E88E5",
    "primary_dark": "#1976D2",
    "primary_darker": "#1565C0",
    "primary_light": "#90CAF9",
    # Status colors
    "success": "#4CAF50",
    "success_text": "#4CAF50",  # For text labels
    "warning": "#FF8C00",
    "warning_text": "#FF8C00",  # For text labels
    "error": "#F44336",
    "info": "#1976D2",
    # Special elements
    "handle": "#A09080",  # Splitter handle
    "tooltip_bg": "#2B2B2B",
    "tooltip_text": "#FFFFFF",
    "tooltip_border": "#555555",
    "white": "#FFFFFF",
    # Collapsible group specific
    "collapsible_header": "#D5CFC4",
    "collapsible_header_hover": "#CEC8BC",
    "collapsible_content": "#E8E3D9",
    "collapsible_border": "#C9C0B0",
    "collapsible_toggle": "#666666",
}

DARK_COLORS: Dict[str, str] = {
    # Backgrounds
    "bg_primary": "#1E1E1E",
    "bg_surface": "#2D2D2D",
    "bg_surface_alt": "#383838",
    "bg_surface_hover": "#424242",
    "bg_surface_pressed": "#303030",
    # Text
    "text_primary": "#E0E0E0",
    "text_secondary": "#A0A0A0",
    "text_tertiary": "#888888",
    "text_disabled": "#666666",
    "text_placeholder": "#808080",
    # Borders
    "border": "#404040",
    "border_light": "#505050",
    # Accent/Brand colors
    "primary": "#2196F3",
    "primary_dark": "#1976D2",
    "primary_darker": "#1565C0",
    "primary_light": "#64B5F6",
    # Status colors (slightly brighter for dark mode)
    "success": "#66BB6A",
    "success_text": "#81C784",  # Brighter green for text
    "warning": "#FFA726",
    "warning_text": "#FFB74D",  # Brighter orange for text
    "error": "#EF5350",
    "info": "#42A5F5",
    # Special elements
    "handle": "#606060",
    "tooltip_bg": "#424242",
    "tooltip_text": "#E0E0E0",
    "tooltip_border": "#606060",
    "white": "#FFFFFF",
    # Collapsible group specific
    "collapsible_header": "#383838",
    "collapsible_header_hover": "#424242",
    "collapsible_content": "#1E1E1E",
    "collapsible_border": "#404040",
    "collapsible_toggle": "#A0A0A0",
}

# =============================================================================
# PLOT COLORS (Consistent across ALL themes - for branding)
# =============================================================================

PLOT_COLORS: Dict[str, str] = {
    # Legacy light aliases; get_plot_color/get_plot_chrome resolve theme-aware chrome.
    "bg": "#F0EBE1",
    "grid": "#D0C9BC",
    # Well log curve colors (from interactive_log.py)
    "GR": "#00AA00",  # Green
    "VSH": "#8B4513",  # Saddle Brown
    "RHOB": "#FF0000",  # Red
    "NPHI": "#0000FF",  # Blue
    "DT": "#FF00FF",  # Magenta
    "RT": "#000000",  # Black
    "SW": "#9400D3",  # Dark Violet
    "PHIE": "#1E90FF",  # Dodger Blue
    "PHID": "#FF6347",  # Tomato
    "PHIN": "#008B8B",  # Dark Cyan
    "PHIT": "#32CD32",  # Lime Green
    "PERM": "#FFD700",  # Gold
    "PERM_TIMUR": "#8B008B",  # Dark Magenta
    "PERM_WR": "#FF8C00",  # Dark Orange
    "PAY": "#228B22",  # Forest Green
    "RESERVOIR": "#FFD700",  # Gold
    "FORMATION_TOP": "#FF6600",  # Orange
    "GAS_CROSSOVER": "#FFD700",  # Gold
    # Sw histogram colors
    "SW_ARCHIE": "#FF6B6B",
    "SW_INDO": "#4ECDC4",
    "SW_SIMAN": "#45B7D1",
    "SW_WS": "#00BFFF",
    "SW_DW": "#8A2BE2",
    "SW_DEFAULT": "#808080",
    # Summary bar chart colors
    "GROSS_SAND": "#2196F3",
    "NET_RESERVOIR": "#4CAF50",
    "NET_PAY": "#FF9800",
    "HCPV": "#228B22",
    # HCPV plot colors (log_display_tab.py)
    "dHCPV_NET_PAY": "#FF4500",
    "HCPV_CUM_NET_PAY": "#228B22",
    "dHCPV_NET_RES": "#DAA520",
    "HCPV_CUM_NET_RES": "#4682B4",
    "dHCPV": "#FF6347",
    "HCPV_CUM": "#00CED1",
    "HCPV_FRAC": "#FF8C00",
    # Crossplot/annotation colors
    "MEDIAN_LINE": "#008000",
    "CORE_POR": "#006666",
    "CORE_PERM": "#CC0000",
    "LOG_PHIE": "#00CED1",
    "LOG_PERM": "#FF6347",
    # Default colors
    "DEFAULT_HISTOGRAM": "#1E90FF",
    "DEFAULT_SCATTER": "#1E90FF",
}

# =============================================================================
# PLOT CHROME
# =============================================================================

# Curve colors are stable across themes; plot chrome follows the active theme.
# RT is the one readability exception: black is retained for light mode,
# while dark mode uses the semantic light text color.
_PLOT_COLOR_OVERRIDES: Dict[str, Dict[str, str]] = {
    "dark": {"RT": DARK_COLORS["text_primary"]},
}

PLOT_CHROME: Dict[str, Dict[str, str]] = {
    "light": {
        "figure": "#F0EBE1",
        "axes": "#F0EBE1",
        "grid": "#D0C9BC",
        "text": "#4A4540",
        "spine": "#C9C0B0",
        "crosshair": "#888888",
        "selection": "#6496C8",
    },
    "dark": {
        "figure": "#1E1E1E",
        "axes": "#2D2D2D",
        "grid": "#505050",
        "text": "#E0E0E0",
        "spine": "#606060",
        "crosshair": "#A0A0A0",
        "selection": "#6496C8",
    },
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

_current_theme = "light"
_VALID_THEMES = frozenset(PLOT_CHROME)


def _normalize_theme(theme: Optional[str]) -> str:
    """Return a supported theme, warning before falling back to light."""
    if theme is None:
        return _current_theme
    if theme not in _VALID_THEMES:
        logger.warning("Unknown theme key %r; falling back to light", theme)
        return "light"
    return theme


def set_current_theme(theme: str) -> str:
    """Set the single module-level theme state and return its normalized value."""
    global _current_theme
    _current_theme = _normalize_theme(theme)
    return _current_theme


def get_current_theme() -> str:
    """Return the normalized current theme used by all color helpers."""
    return _current_theme


def get_color(color_name: str, theme: str = None) -> str:
    """Get a semantic UI color, warning before unknown-key fallback."""
    selected_theme = _normalize_theme(theme)
    colors = DARK_COLORS if selected_theme == "dark" else LIGHT_COLORS
    if color_name not in colors:
        logger.warning("Unknown color key %r; falling back to black", color_name)
        return "#000000"
    return colors[color_name]


def get_plot_color(color_name: str, theme: str = None) -> str:
    """Get a stable curve color or theme-aware legacy plot chrome color."""
    selected_theme = _normalize_theme(theme)
    if color_name == "bg":
        return PLOT_CHROME[selected_theme]["figure"]
    if color_name == "grid":
        return PLOT_CHROME[selected_theme]["grid"]
    override = _PLOT_COLOR_OVERRIDES.get(selected_theme, {}).get(color_name)
    if override is not None:
        return override
    if color_name not in PLOT_COLORS:
        logger.warning("Unknown plot color key %r; falling back to gray", color_name)
        return "#808080"
    return PLOT_COLORS[color_name]


def get_plot_chrome(theme: str = None) -> Dict[str, str]:
    """Return figure/axes/grid/text/spine colors for a plot theme."""
    selected_theme = _normalize_theme(theme)
    return PLOT_CHROME[selected_theme].copy()


def get_colors_dict(theme: str = None) -> Dict[str, str]:
    """Return a copy of the semantic color dictionary for ``theme``."""
    selected_theme = _normalize_theme(theme)
    return (DARK_COLORS if selected_theme == "dark" else LIGHT_COLORS).copy()


def is_dark_theme(theme: str = None) -> bool:
    """Return whether the selected/current theme is dark."""
    return _normalize_theme(theme) == "dark"
