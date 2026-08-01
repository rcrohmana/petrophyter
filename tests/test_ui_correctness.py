import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from matplotlib.colors import to_hex
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from models.app_model import AppModel
from ui.main_window import MainWindow
from ui.tabs.diagnostics_tab import DiagnosticsTab
from ui.tabs.qc_tab import PandasTableModel
from ui.tabs.summary_tab import SummaryTab
from ui.widgets.interactive_log import HAS_PYQTGRAPH, InteractiveLogPlot
from ui.widgets.plot_widget import CompositeLogPlot


@pytest.fixture
def window(qtbot):
    widget = MainWindow()
    qtbot.addWidget(widget)
    yield widget
    widget.close()


def test_session_ui_restores_all_supported_parameter_groups(window):
    model = window.model
    model.analysis_mode = "Per-Formation"
    model.selected_formations = ["Zone A"]
    model.vsh_baseline_method = "Custom (Manual)"
    model.gr_min_manual, model.gr_max_manual = 31.0, 141.0
    model.vsh_methods = ["Larionov Older"]
    model.rho_matrix, model.dt_matrix = 2.71, 49.0
    model.rho_fluid, model.dt_fluid = 1.08, 175.0
    model.shale_approach = "Statistical (Auto)"
    model.rho_shale, model.dt_shale, model.nphi_shale = 2.51, 112.0, 0.41
    model.shale_selection_mode = "quantile"
    model.shale_vsh_threshold = 0.73
    model.shale_vsh_quantile = 0.94
    model.shale_min_points = 77
    model.shale_sweep_tmin, model.shale_sweep_tmax, model.shale_sweep_step = 0.55, 0.85, 0.03
    model.shale_gate_logs, model.shale_iqr_filter = False, False
    model.lithology_preset = "Custom"
    model.a, model.m, model.n = 1.11, 2.31, 2.2
    model.rw, model.rsh = 0.123, 7.4
    model.perm_C, model.perm_P, model.perm_Q = 4321.0, 5.1, 2.7
    model.swirr_method = "Custom" if False else "Buckles Number"
    model.buckles_preset, model.k_buckles = "Custom", 0.037
    model.vsh_cutoff, model.phi_cutoff, model.sw_cutoff = 0.51, 0.13, 0.72
    model.sw_methods = ["Waxman-Smits", "Dual-Water"]
    model.sw_primary_method = "Dual-Water"
    model.ws_qv, model.ws_b, model.dw_swb, model.dw_rwb = 0.44, 1.7, 0.18, 0.33
    model.primary_phie_method = "PHIE_S"
    model.merge_step, model.merge_gap_limit = 1.0, 8.0
    model.core_depth_unit, model.core_max_dist = "FT", 4.5
    model.gas_correction_enabled = True
    model.gas_nphi_factor, model.gas_rhob_factor = 0.4, 0.2

    window._update_ui_from_model()
    sidebar = window.sidebar

    assert sidebar.analysis_mode_widget.get_mode() == "Per-Formation"
    assert sidebar.analysis_mode_widget.get_selected_formations() == ["Zone A"]
    assert sidebar.vsh_params_widget.get_params() == {
        "baseline_method": "Custom (Manual)",
        "gr_min": 31.0,
        "gr_max": 141.0,
        "methods": ["Larionov Older"],
    }
    assert sidebar.matrix_params_widget.get_params() == {"rho_matrix": 2.71, "dt_matrix": 49.0}
    assert sidebar.fluid_params_widget.get_params() == {"rho_fluid": 1.08, "dt_fluid": 175.0}
    shale = sidebar.shale_params_widget.get_params()
    assert shale["approach"] == "Statistical (Auto)"
    assert (shale["rho_shale"], shale["dt_shale"], shale["nphi_shale"]) == (2.51, 112.0, 0.41)
    assert shale["shale_selection_mode"] == "quantile"
    assert shale["shale_vsh_threshold"] == 0.73
    assert shale["shale_vsh_quantile"] == 0.94
    assert shale["shale_min_points"] == 77
    assert shale["shale_gate_logs"] is False and shale["shale_iqr_filter"] is False
    assert sidebar.archie_params_widget.get_params() == {
        "lithology": "Custom", "a": 1.11, "m": 2.31, "n": 2.2
    }
    assert sidebar.res_params_widget.get_params() == {"rw": 0.123, "rsh": 7.4}
    assert sidebar.perm_params_widget.get_params() == {"C": 4321.0, "P": 5.1, "Q": 2.7}
    assert sidebar.swir_params_widget.get_params() == {
        "method": "Buckles Number", "buckles_preset": "Custom", "k_buckles": 0.037
    }
    assert sidebar.cutoff_params_widget.get_params() == {
        "vsh_cutoff": 0.51, "phi_cutoff": 0.13, "sw_cutoff": 0.72
    }
    assert sidebar.sw_models_widget.get_params() == {
        "sw_methods": ["Waxman-Smits", "Dual-Water"],
        "sw_primary_method": "Dual-Water",
        "ws_qv": 0.44, "ws_b": 1.7, "dw_swb": 0.18, "dw_rwb": 0.33,
    }
    assert sidebar.porosity_method_widget.get_params()["primary_phie_method"] == "PHIE_S"
    assert sidebar.merge_step_spin.value() == 1.0
    assert sidebar.merge_gap_spin.value() == 8.0
    assert sidebar.core_unit_combo.currentText() == "FT"
    assert sidebar.core_dist_spin.value() == 4.5
    assert sidebar.gas_correction_widget.get_params() == {
        "enabled": True, "nphi_factor": 0.4, "rhob_factor": 0.2
    }


def test_session_ui_restore_continues_after_one_widget_failure(window, monkeypatch, caplog):
    monkeypatch.setattr(
        window.sidebar.vsh_params_widget,
        "set_params",
        lambda *args: (_ for _ in ()).throw(RuntimeError("broken vsh widget")),
    )
    window.model.rho_matrix = 2.72

    with caplog.at_level(logging.ERROR):
        window._update_ui_from_model()

    assert window.sidebar.matrix_params_widget.rho_matrix_spin.value() == 2.72
    assert "broken vsh widget" in caplog.text


def test_data_invalidation_refreshes_and_clears_every_result_tab(window, monkeypatch):
    window.model._qc_report = None
    window.model._results = None
    window.model._summary = None
    window.model.calculated = False

    window.qc_tab.qc_table_model.set_dataframe(pd.DataFrame({"old": [1]}))
    window.qc_tab.triple_combo_plot.figure.add_subplot(111)
    window.petro_tab.results_table.setVisible(True)
    window.petro_tab.results_model.set_dataframe(pd.DataFrame({"old": [1]}))
    window.log_tab.classic_log.figure.add_subplot(111)
    window.diag_tab.core_group.setVisible(True)
    window.diag_tab.phie_stats_model.set_dataframe(pd.DataFrame({"old": [1]}))
    window.summary_tab.bar_chart.figure.add_subplot(111)
    window.export_tab.preview_table.setVisible(True)
    window.export_tab.preview_model.set_dataframe(pd.DataFrame({"old": [1]}))
    window.export_tab.csv_btn.setEnabled(True)
    window.export_tab.excel_btn.setEnabled(True)

    window._on_data_loaded()

    assert window.qc_tab.qc_table_model.rowCount() == 0
    assert window.qc_tab.triple_combo_plot.figure.axes == []
    assert not window.petro_tab.results_table.isVisible()
    assert window.petro_tab.results_model.rowCount() == 0
    assert window.log_tab.classic_log.figure.axes == []
    assert not window.diag_tab.core_group.isVisible()
    assert window.diag_tab.phie_stats_model.rowCount() == 0
    assert window.summary_tab.bar_chart.figure.axes == []
    assert not window.export_tab.preview_table.isVisible()
    assert window.export_tab.preview_model.rowCount() == 0
    assert not window.export_tab.csv_btn.isEnabled()
    assert not window.export_tab.excel_btn.isEnabled()


def test_stale_results_cannot_drive_perm_or_export(window, monkeypatch):
    window.model._results = pd.DataFrame({"PHIE": np.linspace(0.1, 0.2, 20)})
    window.model._summary = {"net_pay": 1.0}
    window.model.calculated = False
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    csv_calls, excel_calls = [], []
    monkeypatch.setattr(window.export_service, "export_csv", lambda *args: csv_calls.append(args))
    monkeypatch.setattr(window.export_service, "export_excel", lambda *args: excel_calls.append(args))

    window._on_calculate_perm()
    window._on_export_csv("stale.csv")
    window._on_export_excel("stale.xlsx")

    assert warnings == ["Please run analysis first"]
    assert csv_calls == [] and excel_calls == []


def test_run_button_is_disabled_before_analysis_service_starts(window, monkeypatch):
    window.model._las_data = pd.DataFrame({"DEPTH": [100.0]})
    window.sidebar.run_btn.setEnabled(True)
    states = []
    monkeypatch.setattr(window.sidebar, "update_model_from_ui", lambda: None)
    monkeypatch.setattr(
        window.analysis_service,
        "run_analysis",
        lambda model: states.append(window.sidebar.run_btn.isEnabled()),
    )

    window._on_run_analysis()

    assert states == [False]


def test_merge_button_is_disabled_before_merge_service_starts(window, monkeypatch):
    window._loaded_parsers = [object(), object()]
    window._loaded_file_names = ["a.las", "b.las"]
    window.sidebar.merge_btn.setEnabled(True)
    states = []
    monkeypatch.setattr(window.sidebar, "update_model_from_ui", lambda: None)
    monkeypatch.setattr(
        window.merge_service,
        "merge_files",
        lambda *args: states.append(window.sidebar.merge_btn.isEnabled()),
    )

    window._on_merge_requested()

    assert states == [False]


def test_sidebar_reset_restores_whole_well_analysis_mode(window):
    window.sidebar.analysis_mode_widget.per_formation_radio.setChecked(True)
    assert window.sidebar.analysis_mode_widget.get_mode() == "Per-Formation"

    window.sidebar.reset_ui()

    assert window.sidebar.analysis_mode_widget.get_mode() == "Whole Well"


def test_analysis_completion_refreshes_each_tab_once_with_matching_summary(
    window, monkeypatch
):
    calls = []
    for name, tab in (
        ("qc", window.qc_tab),
        ("petro", window.petro_tab),
        ("log", window.log_tab),
        ("diag", window.diag_tab),
        ("summary", window.summary_tab),
        ("export", window.export_tab),
    ):
        monkeypatch.setattr(
            tab,
            "update_display",
            lambda name=name: calls.append(
                (name, window.model.summary and window.model.summary.get("marker"))
            ),
        )
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    results = pd.DataFrame({"DEPTH": [100.0]})
    summary = {"marker": "matching", "net_pay": 0, "gross_sand": 0, "ng_pay": 0}

    window._on_analysis_completed(results, summary)

    assert calls == [
        ("qc", "matching"),
        ("petro", "matching"),
        ("log", "matching"),
        ("diag", "matching"),
        ("summary", "matching"),
        ("export", "matching"),
    ]


def test_single_las_load_syncs_detected_mapping_before_final_qc_refresh(
    window, monkeypatch, tmp_path
):
    import ui.main_window as main_window_module

    class Parser:
        def __init__(self):
            self.data = pd.DataFrame(
                {"DEPTH": [100.0], "GAMMA": [50.0], "RES_DEEP": [10.0]}
            )
            self.well_info = {"well_name": "B"}
            self.depth_unit_warning = None
            self.null_value = -999.25

        def read_las_from_buffer(self, handle):
            return True

        def get_available_curves(self):
            return ["GAMMA", "RES_DEEP"]

        def find_curve_by_type(self, curve_type):
            return {"GR": "GAMMA", "RT": "RES_DEEP"}.get(curve_type)

    report = object()
    monkeypatch.setattr(main_window_module, "LASParser", Parser)
    monkeypatch.setattr(
        main_window_module,
        "QCModule",
        lambda data, well_name: SimpleNamespace(run_qc=lambda: report),
    )
    refresh_states = []
    monkeypatch.setattr(
        window.qc_tab,
        "update_display",
        lambda: refresh_states.append(
            (window.model.qc_report, dict(window.model.curve_mapping))
        ),
    )
    for tab in (
        window.petro_tab,
        window.log_tab,
        window.diag_tab,
        window.summary_tab,
        window.export_tab,
    ):
        monkeypatch.setattr(tab, "update_display", lambda: None)
    las_path = tmp_path / "well.las"
    las_path.write_text("fake", encoding="utf-8")

    window._load_single_las(str(las_path))

    expected = {
        "GR": "GAMMA",
        "RHOB": "None",
        "NPHI": "None",
        "DT": "None",
        "RT": "RES_DEEP",
    }
    assert window.model.curve_mapping == expected
    assert refresh_states[-1] == (report, expected)


def test_log_display_reset_clears_classic_plot(window):
    window.log_tab.classic_log.figure.add_subplot(111)
    assert window.log_tab.classic_log.figure.axes

    window.log_tab.reset_ui()

    assert window.log_tab.classic_log.figure.axes == []


def test_summary_accepts_missing_keys_and_none_metrics(qtbot):
    model = AppModel()
    tab = SummaryTab(model)
    qtbot.addWidget(tab)
    model._calculated = True
    model._summary = {"avg_phie_pay": None, "avg_sw_pay": None, "avg_vsh_pay": None,
                      "hcpv_gross": None, "hcpv_net_res": None, "hcpv_net_pay": None}

    tab.update_display()

    assert tab.gross_sand_card.value_label.text() == "0.0 ft"
    assert tab.avg_phie_card.value_label.text() == "N/A"
    assert tab.hcpv_net_pay_card.value_label.text() == "0.0000 ft"


@pytest.mark.skipif(not HAS_PYQTGRAPH, reason="pyqtgraph unavailable")
def test_interactive_clear_rebinds_visible_crosshairs(qtbot):
    plot = InteractiveLogPlot()
    qtbot.addWidget(plot)

    plot.clear()

    for plot_item, (v_line, h_line) in zip(plot.plot_widgets, plot.crosshairs):
        assert v_line in plot_item.items
        assert h_line in plot_item.items


@pytest.mark.skipif(not HAS_PYQTGRAPH, reason="pyqtgraph unavailable")
def test_interactive_depth_readout_tracks_values_when_input_unsorted(qtbot):
    plot = InteractiveLogPlot()
    qtbot.addWidget(plot)
    data = pd.DataFrame({"DEPTH": [102.0, 100.0, 101.0], "GR": [30.0, 10.0, 20.0]})

    plot.plot_curves(data)

    assert plot._get_values_at_depth(100.0)["GR"] == 10.0


def test_composite_log_plots_all_available_saturation_curves(qtbot):
    plot = CompositeLogPlot()
    qtbot.addWidget(plot)
    data = pd.DataFrame({
        "DEPTH": [100.0, 101.0],
        "PHIE": [0.2, 0.21],
        "PERM_TIMUR": [10.0, 11.0],
        "SW": [0.4, 0.5],
        "SW_ARCHIE": [0.41, 0.51],
        "SW_INDO": [0.42, 0.52],
        "SW_SIMAN": [0.43, 0.53],
        "SW_WS": [0.44, 0.54],
        "SW_DW": [0.45, 0.55],
    })

    plot.plot_petrophysics_summary(data)

    assert {line.get_label() for line in plot.figure.axes[2].lines} == {
        "SW", "ARCHIE", "INDO", "SIMAN", "WS", "DW"
    }


def test_core_validation_uses_configured_max_distance(qtbot, monkeypatch):
    calls = []

    class Core:
        def get_summary(self):
            return {"n_samples": 0, "depth_range": (0, 0), "properties": []}

        def validate_porosity(self, depth, values, max_dist_ft=2.0):
            calls.append(("porosity", max_dist_ft))
            return None

        def validate_permeability(self, depth, values, max_dist_ft=2.0):
            calls.append(("permeability", max_dist_ft))
            return None

    model = AppModel()
    model._calculated = True
    model._results = pd.DataFrame({"DEPTH": [100.0, 101.0], "PHIE": [0.1, 0.2], "PERM_TIMUR": [1.0, 2.0]})
    model._summary = {}
    model.core_data = Core()
    model.core_max_dist = 6.5
    tab = DiagnosticsTab(model)
    qtbot.addWidget(tab)
    monkeypatch.setattr(tab, "_plot_depth_track_with_core", lambda *args: None)

    tab.update_display()

    assert calls == [("porosity", 6.5), ("permeability", 6.5)]


@pytest.mark.parametrize("missing", [np.nan, None, pd.NA])
def test_pandas_table_model_renders_missing_values_blank(qtbot, missing):
    model = PandasTableModel(pd.DataFrame({"value": [missing]}))
    index = model.index(0, 0)

    assert model.data(index, Qt.ItemDataRole.DisplayRole) == ""


def test_core_overlay_failures_are_logged_and_visible(qtbot, caplog):
    class BrokenCore:
        def get_core_porosity(self):
            raise ValueError("bad porosity overlay")

        def get_core_permeability(self):
            raise ValueError("bad permeability overlay")

    model = AppModel()
    tab = DiagnosticsTab(model)
    qtbot.addWidget(tab)
    results = pd.DataFrame({"DEPTH": [100.0], "PHIE": [0.2], "PERM_TIMUR": [1.0]})

    with caplog.at_level(logging.WARNING):
        tab._plot_depth_track_with_core(BrokenCore(), results)

    assert "bad porosity overlay" in caplog.text
    assert "bad permeability overlay" in caplog.text
    assert "Core porosity overlay unavailable" in tab.core_warnings.text()
    assert "Core permeability overlay unavailable" in tab.core_warnings.text()


def test_core_fit_failure_is_logged_before_statistical_fallback(window, caplog):
    class BrokenCore:
        def get_core_permeability(self):
            raise ValueError("bad core fit")

    window.model._results = pd.DataFrame(
        {"PHIE": np.linspace(0.1, 0.2, 20)}
    )
    window.model._calculated = True
    window.model._core_data = BrokenCore()

    with caplog.at_level(logging.ERROR):
        window._on_calculate_perm()

    assert "bad core fit" in caplog.text
    assert "using statistical estimation" in caplog.text


def test_summary_bars_consume_canonical_plot_palette(qtbot, monkeypatch):
    import ui.tabs.summary_tab as summary_module

    colors = {
        "GROSS_SAND": "#110000",
        "NET_RESERVOIR": "#220000",
        "NET_PAY": "#330000",
        "HCPV": "#440000",
    }
    monkeypatch.setattr(
        summary_module, "get_plot_color", lambda key: colors[key], raising=False
    )
    tab = SummaryTab(AppModel())
    qtbot.addWidget(tab)

    tab._update_bar_chart(
        {
            "gross_sand": 4.0,
            "net_reservoir": 3.0,
            "net_pay": 2.0,
            "hcpv_net_pay": 1.0,
        }
    )

    assert [to_hex(patch.get_facecolor()) for patch in tab.bar_chart.figure.axes[0].patches] == [
        color.lower() for color in colors.values()
    ]


def test_hcpv_configs_consume_canonical_plot_palette(window, monkeypatch):
    import ui.tabs.log_display_tab as log_module

    colors = {
        "dHCPV_NET_PAY": "#110000",
        "HCPV_CUM_NET_PAY": "#220000",
        "dHCPV_NET_RES": "#330000",
        "HCPV_CUM_NET_RES": "#440000",
        "dHCPV": "#550000",
        "HCPV_CUM": "#660000",
        "HCPV_FRAC": "#770000",
    }
    monkeypatch.setattr(
        log_module, "get_plot_color", lambda key: colors[key], raising=False
    )
    tab = window.log_tab
    tab.show_hcpv_check.setChecked(True)
    columns = list(colors)
    observed = {}
    for mode in ("Net Pay", "Net Reservoir", "Gross", "Fraction Only"):
        tab.hcpv_mode_combo.setCurrentText(mode)
        observed[mode] = tab._get_hcpv_curve_config(columns)

    assert observed == {
        "Net Pay": [
            ("dHCPV_NET_PAY", colors["dHCPV_NET_PAY"], False, None),
            ("HCPV_CUM_NET_PAY", colors["HCPV_CUM_NET_PAY"], False, None),
        ],
        "Net Reservoir": [
            ("dHCPV_NET_RES", colors["dHCPV_NET_RES"], False, None),
            ("HCPV_CUM_NET_RES", colors["HCPV_CUM_NET_RES"], False, None),
        ],
        "Gross": [
            ("dHCPV", colors["dHCPV"], False, None),
            ("HCPV_CUM", colors["HCPV_CUM"], False, None),
        ],
        "Fraction Only": [
            ("HCPV_FRAC", colors["HCPV_FRAC"], False, (0, 0.5))
        ],
    }


def test_diagnostics_sw_overlay_consumes_canonical_plot_palette(qtbot, monkeypatch):
    import ui.tabs.diagnostics_tab as diagnostics_module

    colors = {
        "SW_ARCHIE": "#110000",
        "SW_INDO": "#220000",
        "SW_SIMAN": "#330000",
    }
    monkeypatch.setattr(
        diagnostics_module, "get_plot_color", lambda key: colors[key], raising=False
    )
    model = AppModel()
    model._calculated = True
    model._results = pd.DataFrame(
        {
            "DEPTH": [100.0, 101.0],
            "SW_ARCHIE": [0.2, 0.3],
            "SW_INDO": [0.3, 0.4],
            "SW_SIMAN": [0.4, 0.5],
        }
    )
    model._summary = {}
    tab = DiagnosticsTab(model)
    qtbot.addWidget(tab)

    tab.update_display()

    patches = tab.sw_hist.figure.axes[0].patches
    assert [to_hex(patches[index].get_facecolor()) for index in (0, 30, 60)] == [
        color.lower() for color in colors.values()
    ]


def test_diagnostics_core_overlay_consumes_canonical_plot_palette(qtbot, monkeypatch):
    import ui.tabs.diagnostics_tab as diagnostics_module

    colors = {
        "LOG_PHIE": "#110000",
        "CORE_POR": "#220000",
        "LOG_PERM": "#330000",
        "CORE_PERM": "#440000",
    }
    monkeypatch.setattr(
        diagnostics_module, "get_plot_color", lambda key: colors[key], raising=False
    )

    class Core:
        def get_core_porosity(self):
            return np.array([100.0]), np.array([0.2])

        def get_core_permeability(self):
            return np.array([100.0]), np.array([10.0])

    tab = DiagnosticsTab(AppModel())
    qtbot.addWidget(tab)
    tab._plot_depth_track_with_core(
        Core(),
        pd.DataFrame(
            {"DEPTH": [100.0], "PHIE": [0.2], "PERM_TIMUR": [10.0]}
        ),
    )

    por_axis = tab.core_phie_depth_plot.figure.axes[0]
    perm_axis = tab.core_perm_depth_plot.figure.axes[0]
    assert to_hex(por_axis.lines[0].get_color()) == colors["LOG_PHIE"].lower()
    assert to_hex(por_axis.collections[0].get_facecolor()[0]) == colors["CORE_POR"].lower()
    assert to_hex(perm_axis.lines[0].get_color()) == colors["LOG_PERM"].lower()
    assert to_hex(perm_axis.collections[0].get_facecolor()[0]) == colors["CORE_PERM"].lower()


def test_shale_approach_change_live_syncs_sidebar_model(window):
    assert window.model.shale_approach == "Custom (Manual)"

    window.sidebar.shale_params_widget.approach_combo.setCurrentText(
        "Statistical (Auto)"
    )

    assert window.model.shale_approach == "Statistical (Auto)"


def test_shale_selection_mode_change_live_syncs_sidebar_model(window):
    assert window.model.shale_selection_mode == "fixed_threshold"

    window.sidebar.shale_params_widget.selection_mode_combo.setCurrentText("Quantile")

    assert window.model.shale_selection_mode == "quantile"
