"""Theme manager for switching between light and dark themes."""

import logging

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from .colors import (
    get_color,
    get_colors_dict,
    get_current_theme,
    get_plot_chrome,
    get_plot_color,
    is_dark_theme,
    set_current_theme,
)
from .dark import DARK_THEME
from .light import LIGHT_THEME


logger = logging.getLogger(__name__)


class ThemeManager:
    """Manages application theme switching and change notifications."""

    LIGHT = "light"
    DARK = "dark"

    def __init__(self, app: QApplication, icons_dir: str):
        self.app = app
        self.icons_dir = icons_dir
        self.settings = QSettings("Petrophyter Team", "Petrophyter")
        self._legacy_settings = QSettings("Petrophyter", "Theme")
        saved_theme = self.settings.value("theme/name", None, type=str)
        if not saved_theme:
            saved_theme = self._legacy_settings.value("theme", self.LIGHT, type=str)
        if saved_theme not in (self.LIGHT, self.DARK):
            logger.warning("Unknown persisted theme %r; falling back to light", saved_theme)
            saved_theme = self.LIGHT
        set_current_theme(saved_theme)
        self._theme_changed_callbacks = []

    def get_current_theme(self) -> str:
        """Get the canonical current theme name."""
        return get_current_theme()

    def set_theme(self, theme: str):
        """Apply a theme and notify registered callbacks."""
        if theme not in (self.LIGHT, self.DARK):
            logger.warning("Unknown theme key %r; falling back to light", theme)
            theme = self.LIGHT

        set_current_theme(theme)
        self.settings.setValue("theme/name", theme)

        colors = get_colors_dict(theme)
        stylesheet = LIGHT_THEME if theme == self.LIGHT else DARK_THEME

        # Apply the palette from the canonical semantic colors.
        palette = self.app.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(colors["bg_primary"]))
        palette.setColor(QPalette.ColorRole.Base, QColor(colors["bg_surface"]))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colors["bg_surface_alt"]))
        palette.setColor(QPalette.ColorRole.Text, QColor(colors["text_primary"]))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(colors["text_primary"]))
        palette.setColor(QPalette.ColorRole.Button, QColor(colors["bg_surface_alt"]))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors["text_primary"]))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(colors["tooltip_bg"]))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(colors["tooltip_text"]))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(colors["text_placeholder"]))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(colors["primary"]))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(colors["white"]))
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.Text,
            QColor(colors["text_disabled"]),
        )
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.WindowText,
            QColor(colors["text_disabled"]),
        )
        self.app.setPalette(palette)

        # Preserve the existing stylesheet structure; only substitute the
        # explicit tooltip token and icon path in this staged-safe change.
        final_stylesheet = stylesheet.replace(
            "border: 1px solid #555555;",
            f"border: 1px solid {colors['tooltip_border']};",
        ).replace(
            "border: 1px solid #606060;",
            f"border: 1px solid {colors['tooltip_border']};",
        ).replace("{{ICONS_DIR}}", self.icons_dir)
        self.app.setStyleSheet(final_stylesheet)

        for callback in list(self._theme_changed_callbacks):
            try:
                callback(theme)
            except RuntimeError:
                logger.warning("Theme callback target is no longer available", exc_info=True)
            except Exception:
                logger.exception("Theme callback failed")

    def toggle_theme(self):
        """Toggle between light and dark themes."""
        new_theme = self.DARK if not is_dark_theme() else self.LIGHT
        self.set_theme(new_theme)
        return new_theme

    def on_theme_changed(self, callback):
        """Register a callback invoked after the theme is applied."""
        self._theme_changed_callbacks.append(callback)

    def is_dark(self) -> bool:
        """Check the canonical theme state."""
        return is_dark_theme()

    def get_color(self, color_name: str) -> str:
        """Get a semantic color for the canonical current theme."""
        return get_color(color_name)

    def get_colors(self) -> dict:
        """Get semantic colors for the canonical current theme."""
        return get_colors_dict()

    def get_plot_color(self, color_name: str) -> str:
        """Get a stable curve color or current-theme plot chrome color."""
        return get_plot_color(color_name)

    def get_plot_chrome(self) -> dict:
        """Get current-theme matplotlib/pyqtgraph chrome colors."""
        return get_plot_chrome()
