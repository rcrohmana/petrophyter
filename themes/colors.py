"""
Centralized color definitions for Petrophyter themes.
All colors should be accessed through get_color() or get_plot_color() functions.

This ensures consistent theming across the application and makes it easy
to maintain and update color schemes.
"""

from typing import Dict

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
    "success_text": "green",  # For text labels
    "warning": "#FF8C00",
    "warning_text": "orange",  # For text labels
    "error": "#F44336",
    "info": "#1976D2",
    # Special elements
    "handle": "#A09080",  # Splitter handle
    "tooltip_bg": "#2B2B2B",
    "tooltip_text": "#FFFFFF",
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
    # Plot background - ALWAYS sand for branding consistency
    "bg": "#F0EBE1",
    "grid": "#D0C9BC",
    # Well log curve colors (from interactive_log.py)
    "GR": "#228B22",  # Forest Green
    "VSH": "#8B4513",  # Saddle Brown
    "RHOB": "#FF0000",  # Red
    "NPHI": "#0000FF",  # Blue
    "DT": "#800080",  # Purple
    "RT": "#FF8C00",  # Dark Orange
    "SW": "#00CED1",  # Dark Cyan
    "PHIE": "#FFD700",  # Gold
    "PERM": "#FF1493",  # Deep Pink
    # Sw histogram colors
    "SW_ARCHIE": "#FF6B6B",
    "SW_INDO": "#4ECDC4",
    "SW_SIMAN": "#45B7D1",
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
    "MEDIAN_LINE": "green",
    "CORE_POR": "#006666",
    "CORE_PERM": "#CC0000",
    "LOG_PHIE": "#00CED1",
    "LOG_PERM": "#FF6347",
    # Default colors
    "DEFAULT_HISTOGRAM": "#1E90FF",
    "DEFAULT_SCATTER": "#1E90FF",
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

_current_theme = "light"


def set_current_theme(theme: str):
    """
    Set the current theme for color lookups.

    Args:
        theme: Theme name ('light' or 'dark')
    """
    global _current_theme
    _current_theme = theme


def get_color(color_name: str, theme: str = None) -> str:
    """
    Get color value for the specified color name.

    Args:
        color_name: Semantic color name (e.g., 'text_primary', 'bg_surface')
        theme: Optional theme override ('light' or 'dark').
               If None, uses current theme.

    Returns:
        Color hex string (e.g., '#E8E3D9')

    Example:
        >>> get_color('bg_primary')  # Uses current theme
        '#E8E3D9'
        >>> get_color('bg_primary', 'dark')  # Explicit dark theme
        '#1E1E1E'
    """
    if theme is None:
        theme = _current_theme

    colors = DARK_COLORS if theme == "dark" else LIGHT_COLORS
    return colors.get(color_name, LIGHT_COLORS.get(color_name, "#000000"))


def get_plot_color(color_name: str) -> str:
    """
    Get plot color value (consistent across all themes).

    Plot colors remain the same in both light and dark themes
    for branding consistency and plotting convention.

    Args:
        color_name: Plot color name (e.g., 'GR', 'SW_ARCHIE', 'bg')

    Returns:
        Color hex string

    Example:
        >>> get_plot_color('bg')  # Plot background (always sand)
        '#F0EBE1'
        >>> get_plot_color('GR')  # Gamma Ray curve
        '#228B22'
    """
    return PLOT_COLORS.get(color_name, "#808080")


def get_colors_dict(theme: str = None) -> Dict[str, str]:
    """
    Get the full colors dictionary for the specified theme.

    Args:
        theme: Theme name ('light' or 'dark'). If None, uses current theme.

    Returns:
        Dictionary of all color definitions for the theme
    """
    if theme is None:
        theme = _current_theme
    return DARK_COLORS.copy() if theme == "dark" else LIGHT_COLORS.copy()


def is_dark_theme(theme: str = None) -> bool:
    """
    Check if current or specified theme is dark.

    Args:
        theme: Theme name to check. If None, uses current theme.

    Returns:
        True if dark theme, False otherwise
    """
    if theme is None:
        theme = _current_theme
    return theme == "dark"
