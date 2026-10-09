# tests/test_design_tokens.py
"""Token integrity tests (§3 of the design spec)."""
import re

from themes import tokens
from themes.renderer import render_qss


HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def test_theme_key_parity():
    assert tokens.COLORS["light"].keys() == tokens.COLORS["dark"].keys()


def test_all_colors_are_hex():
    for theme in ("light", "dark"):
        for key, value in tokens.COLORS[theme].items():
            assert HEX_RE.match(value), f"{theme}.{key} = {value!r}"


def test_accent_values():
    assert tokens.COLORS["light"]["accent"] == "#3D6E96"
    assert tokens.COLORS["dark"]["accent"] == "#5B8DB8"


def test_curve_colors_unchanged():
    # Industry-convention colors must survive the migration verbatim.
    assert tokens.PLOT_COLORS["GR"] == "#00AA00"
    assert tokens.PLOT_COLORS["RHOB"] == "#FF0000"
    assert tokens.PLOT_COLORS["NPHI"] == "#0000FF"
    assert tokens.PLOT_COLORS["RT"] == "#000000"
    assert tokens.PLOT_COLORS["SW"] == "#9400D3"


def test_plot_chrome_derived_from_ui_palette():
    for theme in ("light", "dark"):
        assert tokens.PLOT_CHROME[theme]["figure"] == tokens.COLORS[theme]["bg_surface"]


def test_typography_scale():
    assert tokens.TYPOGRAPHY["font_caption"] == 8
    assert tokens.TYPOGRAPHY["font_body"] == 9
    assert tokens.TYPOGRAPHY["font_subheading"] == 10
    assert tokens.TYPOGRAPHY["font_max"] == 11
    assert max(v for k, v in tokens.TYPOGRAPHY.items() if k.startswith("font_") and isinstance(v, int)) <= 11


def test_qss_renders_without_residue():
    for theme in ("light", "dark"):
        qss = render_qss(theme)
        assert "$" not in qss, "unresolved $token placeholder in rendered QSS"
        assert tokens.COLORS[theme]["bg_base"] in qss


def test_qss_unknown_theme_raises():
    import pytest
    with pytest.raises(KeyError):
        render_qss("solarized")
