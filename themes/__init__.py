"""
Theme system for Petrophyter PyQt.
Provides light and dark theme support with centralized color management.
"""

from . import tokens
from .colors import (
    PLOT_COLORS,
    PLOT_CHROME,
    get_color,
    get_plot_color,
    get_plot_chrome,
    set_current_theme,
    get_current_theme,
    get_colors_dict,
    is_dark_theme,
)
from .helpers import set_status, set_variant
from .icon_loader import clear_icon_cache, get_icon
from .renderer import render_qss
from .theme_manager import ThemeManager

__all__ = [
    "ThemeManager",
    "tokens",
    "render_qss",
    "get_icon",
    "clear_icon_cache",
    "set_status",
    "set_variant",
    "PLOT_COLORS",
    "PLOT_CHROME",
    "get_color",
    "get_plot_color",
    "get_plot_chrome",
    "set_current_theme",
    "get_current_theme",
    "get_colors_dict",
    "is_dark_theme",
]
