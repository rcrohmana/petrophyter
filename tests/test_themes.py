"""Behavioral regressions for staged-safe theme and plot consolidation."""

import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
import pytest
from PyQt6.QtWidgets import QApplication

from themes.colors import (
    DARK_COLORS,
    LIGHT_COLORS,
    PLOT_COLORS,
    get_color,
    get_current_theme,
    get_plot_chrome,
    get_plot_color,
    is_dark_theme,
    set_current_theme,
)
from themes.theme_manager import ThemeManager
from ui.tabs.qc_tab import QCTab
from ui.widgets.interactive_log import InteractiveLogPlot
from ui.widgets.plot_widget import PlotWidget, TripleComboPlot


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


class TestThemeColors:
    def test_plot_palette_uses_interactive_curve_values_except_rt_override(self):
        expected = {
            "GR": "#00AA00",
            "VSH": "#8B4513",
            "RHOB": "#FF0000",
            "NPHI": "#0000FF",
            "DT": "#FF00FF",
            "SW": "#9400D3",
            "PHIE": "#1E90FF",
            "PERM": "#FFD700",
            "PHID": "#FF6347",
            "PHIN": "#008B8B",
            "PAY": "#228B22",
        }

        assert {key: PLOT_COLORS[key] for key in expected} == expected
        assert all(get_plot_color(key, "light") == value for key, value in expected.items())
        assert all(get_plot_color(key, "dark") == value for key, value in expected.items())

    def test_rt_color_is_light_in_dark_theme_but_black_in_light_theme(self):
        assert get_plot_color("RT", "light") == "#000000"
        assert get_plot_color("RT", "dark") == DARK_COLORS["text_primary"]
        assert get_plot_color("RT", "dark") != get_plot_color("RT", "light")

    def test_plot_chrome_is_deterministic_and_theme_aware(self):
        light = get_plot_chrome("light")
        dark = get_plot_chrome("dark")
        required = {"figure", "axes", "grid", "text", "spine"}

        assert required <= light.keys()
        assert required <= dark.keys()
        assert light != dark
        assert light["figure"] == "#F0EBE1"
        assert dark["figure"] == "#1E1E1E"
        assert light["text"] != dark["text"]
        assert get_plot_color("bg", "dark") == dark["figure"]
        assert get_plot_color("grid", "dark") == dark["grid"]

    def test_unknown_theme_and_color_warn_before_safe_fallback(self, caplog):
        with caplog.at_level(logging.WARNING):
            assert get_color("does_not_exist", "light") == "#000000"
            assert get_plot_color("does_not_exist") == "#808080"
            assert get_color("text_primary", "sepia") == LIGHT_COLORS["text_primary"]
            assert get_plot_chrome("sepia") == get_plot_chrome("light")

        assert "unknown color key" in caplog.text.lower()
        assert "unknown theme" in caplog.text.lower()

    def test_css_names_are_normalized_and_tooltip_token_exists(self):
        assert LIGHT_COLORS["success_text"].startswith("#")
        assert LIGHT_COLORS["warning_text"].startswith("#")
        assert PLOT_COLORS["MEDIAN_LINE"].startswith("#")
        assert "tooltip_border" in LIGHT_COLORS
        assert "tooltip_border" in DARK_COLORS

    def test_palette_module_aliases_remain_compatible(self):
        from themes.light import LIGHT_COLORS as light_palette
        from themes.light import LIGHT_PALETTE
        from themes.dark import DARK_COLORS as dark_palette
        from themes.dark import DARK_PALETTE

        assert light_palette is LIGHT_PALETTE
        assert dark_palette is DARK_PALETTE
        assert light_palette["background"] == LIGHT_COLORS["bg_primary"]
        assert dark_palette["background"] == DARK_COLORS["bg_primary"]


class TestThemeManager:
    def test_manager_flow_is_single_source_for_theme_state(self, qapp, tmp_path):
        manager = ThemeManager(qapp, str(tmp_path))
        manager.set_theme("light")
        received = []
        manager.on_theme_changed(received.append)

        manager.set_theme("dark")

        assert received[-1] == "dark"
        assert manager.get_current_theme() == get_current_theme() == "dark"
        assert manager.is_dark() is is_dark_theme() is True
        assert manager.get_color("bg_primary") == DARK_COLORS["bg_primary"]
        assert manager.get_plot_color("PHIE") == PLOT_COLORS["PHIE"]
        assert manager.get_plot_color("RT") == DARK_COLORS["text_primary"]

    def test_invalid_theme_warns_and_falls_back_to_light(self, qapp, caplog, tmp_path):
        manager = ThemeManager(qapp, str(tmp_path))

        with caplog.at_level(logging.WARNING):
            manager.set_theme("Dark")

        assert manager.get_current_theme() == "light"
        assert "unknown theme" in caplog.text.lower()

    def test_legacy_callback_failure_does_not_block_other_callbacks(self, qapp, caplog, tmp_path):
        manager = ThemeManager(qapp, str(tmp_path))
        received = []

        def broken_callback(_theme):
            raise RuntimeError("destroyed widget")

        manager.on_theme_changed(broken_callback)
        manager.on_theme_changed(received.append)
        with caplog.at_level(logging.WARNING):
            manager.set_theme("dark")

        assert received == ["dark"]
        assert "callback target" in caplog.text.lower()
        manager.set_theme("light")

    def test_legacy_qsettings_theme_is_read_during_migration(self, monkeypatch, qapp, tmp_path):
        class FakeSettings:
            instances = []

            def __init__(self, organization, application):
                self.identity = (organization, application)
                self.values = {}
                self.instances.append(self)

            def value(self, key, default=None, type=None):
                if self.identity == ("Petrophyter", "Theme") and key == "theme":
                    return "dark"
                return self.values.get(key, default)

            def setValue(self, key, value):
                self.values[key] = value

        monkeypatch.setattr("themes.theme_manager.QSettings", FakeSettings)
        manager = ThemeManager(qapp, str(tmp_path))

        assert manager.get_current_theme() == "dark"
        assert ("Petrophyter Team", "Petrophyter") in [
            instance.identity for instance in FakeSettings.instances
        ]
        manager.set_theme("light")


class TestPlotConsumers:
    def test_plot_widget_applies_theme_chrome_without_changing_curves(self, qapp):
        set_current_theme("dark")
        widget = PlotWidget(show_toolbar=False)
        widget.update_theme_colors()
        ax = widget.get_axes()

        chrome = get_plot_chrome("dark")
        assert widget._bg_color == chrome["figure"]
        assert widget._axes_color == chrome["axes"]
        assert widget.figure.get_facecolor()[:3] == pytest.approx(
            tuple(int(chrome["figure"][i : i + 2], 16) / 255 for i in (1, 3, 5)),
            abs=0.01,
        )
        assert ax.get_facecolor()[:3] == pytest.approx(
            tuple(int(chrome["axes"][i : i + 2], 16) / 255 for i in (1, 3, 5)),
            abs=0.01,
        )
        widget.deleteLater()
        set_current_theme("light")

    def test_interactive_default_config_resolves_rt_for_current_theme(self, qapp):
        widget = InteractiveLogPlot(n_tracks=6)
        columns = [
            "DEPTH", "GR", "VSH", "PHIE", "PHID", "PHIN", "SW", "RT",
            "PERM", "NET_PAY_FLAG",
        ]

        set_current_theme("light")
        light_config = widget._default_curve_config(columns)
        light_colors = {
            curve: color
            for curves in light_config.values()
            for curve, color, *_ in curves
        }

        set_current_theme("dark")
        dark_config = widget._default_curve_config(columns)
        dark_colors = {
            curve: color
            for curves in dark_config.values()
            for curve, color, *_ in curves
        }

        assert light_colors["RT"] == "#000000"
        assert dark_colors["RT"] == DARK_COLORS["text_primary"]
        assert light_colors["GR"] == dark_colors["GR"] == PLOT_COLORS["GR"]
        assert light_colors["PHIE"] == dark_colors["PHIE"] == PLOT_COLORS["PHIE"]
        widget.deleteLater()
        set_current_theme("light")

    def test_qc_tab_refreshes_triple_combo(self, qapp):
        tab = QCTab(None)
        calls = []

        class SpyPlot:
            def refresh_theme(self):
                calls.append("refreshed")

        tab.triple_combo_plot = SpyPlot()
        tab.refresh_theme()

        assert calls == ["refreshed"]
        tab.deleteLater()

    def test_triple_combo_rt_artist_tracks_theme_without_changing_other_curves(self, qapp):
        data = pd.DataFrame({
            "DEPTH": [1000.0, 1001.0, 1002.0],
            "GR": [40.0, 50.0, 60.0],
            "RT": [2.0, 4.0, 8.0],
            "RHOB": [2.2, 2.25, 2.3],
            "NPHI": [0.25, 0.2, 0.15],
        })
        mapping = {key: key for key in ("GR", "RT", "RHOB", "NPHI")}
        widget = TripleComboPlot()

        set_current_theme("light")
        widget.plot_triple_combo(data, mapping)
        light_rt = widget.figure.axes[1].lines[0].get_color()
        light_gr = widget.figure.axes[0].lines[0].get_color()

        set_current_theme("dark")
        widget.refresh_theme()
        dark_rt = widget.figure.axes[1].lines[0].get_color()
        dark_gr = widget.figure.axes[0].lines[0].get_color()

        assert light_rt == "#000000"
        assert dark_rt == DARK_COLORS["text_primary"]
        assert dark_rt != light_rt
        assert light_gr == dark_gr == PLOT_COLORS["GR"]
        widget.deleteLater()
        set_current_theme("light")
