"""
Centralized color definitions for Petrophyter themes.
All colors should be accessed through get_color() or get_plot_color() functions.

This ensures consistent theming across the application and makes it easy
to maintain and update color schemes.
"""

import logging
from typing import Dict, Optional

from .tokens import COLORS, PLOT_CHROME, PLOT_COLOR_OVERRIDES, PLOT_COLORS


logger = logging.getLogger(__name__)

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
    colors = COLORS["dark" if selected_theme == "dark" else "light"]
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
    override = PLOT_COLOR_OVERRIDES.get(selected_theme, {}).get(color_name)
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
    return COLORS["dark" if selected_theme == "dark" else "light"].copy()


def is_dark_theme(theme: str = None) -> bool:
    """Return whether the selected/current theme is dark."""
    return _normalize_theme(theme) == "dark"
