"""Render the QSS template for a theme. Raises on any unresolved token."""
from string import Template

from .template import QSS_TEMPLATE
from .tokens import COLORS, METRICS, SPACING, TYPOGRAPHY


def _context(theme: str, qss_icon_dir: str) -> dict:
    ctx = dict(COLORS[theme])  # KeyError on unknown theme — intended
    ctx["font_family"] = TYPOGRAPHY["font_family"]
    ctx["font_mono"] = TYPOGRAPHY["font_mono"]
    for key in ("font_caption", "font_body", "font_subheading", "font_max"):
        ctx[key] = f"{TYPOGRAPHY[key]}pt"
    for key, value in SPACING.items():
        ctx[f"space_{key}"] = f"{value}px"
    ctx["radius"] = f"{METRICS['radius']}px"
    ctx["control_height"] = f"{METRICS['control_height']}px"
    ctx["toolbar_height"] = f"{METRICS['toolbar_height']}px"
    ctx["scrollbar_width"] = f"{METRICS['scrollbar_width']}px"
    ctx["qss_icons"] = qss_icon_dir
    return ctx


def render_qss(theme: str, qss_icon_dir: str = "") -> str:
    # substitute() raises KeyError on a missing token — that is the
    # "no unresolved placeholder" guarantee the compliance test relies on.
    return Template(QSS_TEMPLATE).substitute(_context(theme, qss_icon_dir))
