"""
Theme manager for switching between light and dark themes.
"""

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import QSettings

from .light import LIGHT_THEME, LIGHT_COLORS
from .dark import DARK_THEME, DARK_COLORS
from .colors import (
    get_color,
    get_plot_color,
    set_current_theme,
    get_colors_dict,
    is_dark_theme,
    PLOT_COLORS,
)


class ThemeManager:
    """Manages application theme switching."""

    LIGHT = "light"
    DARK = "dark"

    def __init__(self, app: QApplication, icons_dir: str):
        self.app = app
        self.icons_dir = icons_dir
        self.settings = QSettings("Petrophyter", "Theme")
        self._current_theme = self.settings.value("theme", self.LIGHT)
        self._theme_changed_callbacks = []

    def get_current_theme(self) -> str:
        """Get the current theme name."""
        return self._current_theme

    def set_theme(self, theme: str):
        """Apply the specified theme."""
        if theme not in [self.LIGHT, self.DARK]:
            theme = self.LIGHT

        self._current_theme = theme
        self.settings.setValue("theme", theme)

        # Update global current theme for color lookups
        set_current_theme(theme)

        colors = LIGHT_COLORS if theme == self.LIGHT else DARK_COLORS
        stylesheet = LIGHT_THEME if theme == self.LIGHT else DARK_THEME

        # Apply palette
        palette = self.app.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(colors["background"]))
        palette.setColor(QPalette.ColorRole.Base, QColor(colors["surface"]))
        palette.setColor(
            QPalette.ColorRole.AlternateBase, QColor(colors["surface_alt"])
        )
        palette.setColor(QPalette.ColorRole.Text, QColor(colors["text"]))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(colors["text"]))
        palette.setColor(QPalette.ColorRole.Button, QColor(colors["surface_alt"]))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors["text"]))
        self.app.setPalette(palette)

        # Apply stylesheet
        final_stylesheet = stylesheet.replace("{{ICONS_DIR}}", self.icons_dir)
        self.app.setStyleSheet(final_stylesheet)

        # Notify callbacks
        for callback in self._theme_changed_callbacks:
            callback(theme)

    def toggle_theme(self):
        """Toggle between light and dark themes."""
        new_theme = self.DARK if self._current_theme == self.LIGHT else self.LIGHT
        self.set_theme(new_theme)
        return new_theme

    def on_theme_changed(self, callback):
        """Register a callback for theme changes."""
        self._theme_changed_callbacks.append(callback)

    def is_dark(self) -> bool:
        """Check if current theme is dark."""
        return self._current_theme == self.DARK

    def get_color(self, color_name: str) -> str:
        """
        Get color value for current theme.

        Args:
            color_name: Semantic color name (e.g., 'text_primary', 'bg_surface')

        Returns:
            Color hex string
        """
        return get_color(color_name, self._current_theme)

    def get_colors(self) -> dict:
        """
        Get all colors for current theme.

        Returns:
            Dictionary of all color definitions
        """
        return get_colors_dict(self._current_theme)

    def get_plot_color(self, color_name: str) -> str:
        """
        Get plot color value (consistent across themes).

        Args:
            color_name: Plot color name

        Returns:
            Color hex string
        """
        return get_plot_color(color_name)
