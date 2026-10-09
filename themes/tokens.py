"""Design tokens — the ONLY file in the codebase allowed to contain UI colors.

Mirrored by docs/design.md. tokens.py is the source of truth.
"""

COLORS = {
    "light": {
        "bg_base": "#F0F2F4",
        "bg_surface": "#FFFFFF",
        "bg_sunken": "#E8EAED",
        "bg_hover": "#E9EBEE",
        "bg_pressed": "#DFE2E6",
        "border": "#D5D9DE",
        "border_strong": "#B8BEC5",
        "text_primary": "#1F2328",
        "text_secondary": "#57606A",
        "text_muted": "#798089",
        "text_disabled": "#A5ABB3",
        "text_on_accent": "#FFFFFF",
        "accent": "#3D6E96",
        "accent_hover": "#356185",
        "accent_pressed": "#2E5677",
        "accent_subtle": "#E4EDF4",
        "accent_muted": "#9EB6CA",
        "focus_ring": "#8FB0CC",
        "success": "#2E7D46",
        "success_subtle": "#E6F2EA",
        "warning": "#B26A00",
        "warning_subtle": "#F7EEDF",
        "error": "#B3382E",
        "error_subtle": "#F6E7E5",
        "tooltip_bg": "#2B2F34",
        "tooltip_text": "#F0F2F4",
    },
    "dark": {
        "bg_base": "#17191D",
        "bg_surface": "#1F2227",
        "bg_sunken": "#131518",
        "bg_hover": "#262A30",
        "bg_pressed": "#2C3138",
        "border": "#2E3238",
        "border_strong": "#3D434B",
        "text_primary": "#D5D9DE",
        "text_secondary": "#9AA1A9",
        "text_muted": "#6E757D",
        "text_disabled": "#4E545B",
        "text_on_accent": "#FFFFFF",
        "accent": "#5B8DB8",
        "accent_hover": "#6C9CC4",
        "accent_pressed": "#4A7CA6",
        "accent_subtle": "#243240",
        "accent_muted": "#3D5F7F",
        "focus_ring": "#7DA5C9",
        "success": "#57A773",
        "success_subtle": "#1E2C23",
        "warning": "#C98A2E",
        "warning_subtle": "#2E271B",
        "error": "#C75E55",
        "error_subtle": "#2E1F1E",
        "tooltip_bg": "#33383F",
        "tooltip_text": "#E4E7EA",
    },
}

TYPOGRAPHY = {
    "font_family": "Segoe UI",
    "font_mono": "Consolas",
    "font_caption": 8,
    "font_body": 9,
    "font_subheading": 10,
    "font_max": 11,
}

SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}

METRICS = {
    "radius": 3,
    "control_height": 26,
    "toolbar_height": 34,
    "panel_min_width": 220,      # Data Browser (spec §3.4)
    "panel_default_width": 300,
    "panel_max_width": 320,
    "params_window_width": 640,  # Parameters window (spec §2.5)
    "params_window_height": 560,
    "params_window_min_width": 560,
    "params_window_min_height": 420,
    "params_page_list_width": 180,
    # QMenu geometry (F9): text starts menu_icon_column px from the menu edge
    # (8 margin + 16 icon + 12 gap); icon box starts menu_icon_margin px from it.
    # Qt adds its own 20 px icon column to the item padding (measured, Qt 6.9 Fusion).
    "menu_icon_column": 36,
    "menu_icon_margin": 8,
    "menu_qt_icon_column": 20,
    "splitter_handle": 4,
    "scrollbar_width": 10,
}

# Curve colors: industry convention, theme-independent, values copied VERBATIM
# from the current themes/colors.py PLOT_COLORS dict, plus new named entries
# for colors previously hardcoded in ui/ (GR_FILL was #90EE90 in plot_widget.py).
PLOT_COLORS = {
    "bg": "#F0EBE1",
    "grid": "#D0C9BC",
    "GR": "#00AA00",
    "VSH": "#8B4513",
    "RHOB": "#FF0000",
    "NPHI": "#0000FF",
    "DT": "#FF00FF",
    "RT": "#000000",
    "SW": "#9400D3",
    "PHIE": "#1E90FF",
    "PHID": "#FF6347",
    "PHIN": "#008B8B",
    "PHIT": "#32CD32",
    "PERM": "#FFD700",
    "PERM_TIMUR": "#8B008B",
    "PERM_WR": "#FF8C00",
    "PAY": "#228B22",
    "RESERVOIR": "#FFD700",
    "FORMATION_TOP": "#FF6600",
    "GAS_CROSSOVER": "#FFD700",
    "SW_ARCHIE": "#FF6B6B",
    "SW_INDO": "#4ECDC4",
    "SW_SIMAN": "#45B7D1",
    "SW_WS": "#00BFFF",
    "SW_DW": "#8A2BE2",
    "SW_DEFAULT": "#808080",
    "GROSS_SAND": "#2196F3",
    "NET_RESERVOIR": "#4CAF50",
    "NET_PAY": "#FF9800",
    "HCPV": "#228B22",
    "dHCPV_NET_PAY": "#FF4500",
    "HCPV_CUM_NET_PAY": "#228B22",
    "dHCPV_NET_RES": "#DAA520",
    "HCPV_CUM_NET_RES": "#4682B4",
    "dHCPV": "#FF6347",
    "HCPV_CUM": "#00CED1",
    "HCPV_FRAC": "#FF8C00",
    "MEDIAN_LINE": "#008000",
    "CORE_POR": "#006666",
    "CORE_PERM": "#CC0000",
    "LOG_PHIE": "#00CED1",
    "LOG_PERM": "#FF6347",
    "DEFAULT_HISTOGRAM": "#1E90FF",
    "DEFAULT_SCATTER": "#1E90FF",
    "GR_FILL": "#90EE90",
    "RES_FILL": "#FFFF00",
}

PLOT_CHROME = {
    "light": {
        "figure": COLORS["light"]["bg_surface"],
        "axes": COLORS["light"]["bg_surface"],
        "grid": COLORS["light"]["border"],
        "text": COLORS["light"]["text_secondary"],
        "spine": COLORS["light"]["border_strong"],
        "crosshair": COLORS["light"]["text_muted"],
        "selection": COLORS["light"]["accent"],
    },
    "dark": {
        "figure": COLORS["dark"]["bg_surface"],
        "axes": COLORS["dark"]["bg_surface"],
        "grid": COLORS["dark"]["border"],
        "text": COLORS["dark"]["text_secondary"],
        "spine": COLORS["dark"]["border_strong"],
        "crosshair": COLORS["dark"]["text_muted"],
        "selection": COLORS["dark"]["accent"],
    },
}

# RT is drawn black by convention; unreadable on dark backgrounds.
PLOT_COLOR_OVERRIDES = {"dark": {"RT": COLORS["dark"]["text_primary"]}}
