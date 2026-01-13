"""
Theme system for Petrophyter PyQt.
Provides light and dark theme support with centralized color management.
"""

from .colors import (
    LIGHT_COLORS,
    DARK_COLORS,
    PLOT_COLORS,
    get_color,
    get_plot_color,
    set_current_theme,
    get_colors_dict,
    is_dark_theme,
)
from .theme_manager import ThemeManager
from .light import LIGHT_THEME
from .dark import DARK_THEME

__all__ = [
    "ThemeManager",
    "LIGHT_THEME",
    "DARK_THEME",
    "LIGHT_COLORS",
    "DARK_COLORS",
    "PLOT_COLORS",
    "get_color",
    "get_plot_color",
    "set_current_theme",
    "get_colors_dict",
    "is_dark_theme",
]
