"""Strict regressions for the modules/services follow-up task."""

import io
import logging

import lasio
import numpy as np
import pandas as pd
import pytest

from models.app_model import AppModel
from modules.las_handler import export_merged_las
from modules.las_parser import LASParser
from modules.petrophysics import PetrophysicsCalculator
from modules.qc_module import QCModule
from services.analysis_service import AnalysisWorker


@pytest.fixture
def main_window(qtbot):
    from ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    yield window
    window.close()


def _run_worker(model):
    completed = []
    errors = []
    worker = AnalysisWorker(model)
    worker.signals.completed.connect(
        lambda results, summary: completed.append((results, summary))
    )
    worker.signals.error.connect(errors.append)
    worker.run()
    assert not errors, errors
    assert len(completed) == 1
    return completed[0]


def _model_for_matrix(data, nphi_matrix):
    model = AppModel()
    model.las_data = data
    model.curve_mapping = {
        "GR": "GR",
        "RHOB": "RHOB",
        "NPHI": "NPHI",
        "DT": "None",
        "RT": "RT",
    }
    model.vsh_baseline_method = "Custom (Manual)"
    model.gr_min_manual = 20.0
    model.gr_max_manual = 120.0
    model.nphi_matrix = nphi_matrix
    return model


def test_analysis_worker_uses_configured_nphi_matrix_value():
    data = pd.DataFrame(
        {
            "DEPTH": [1000.0, 1001.0],
            "GR": [30.0, 90.0],
            "RHOB": [2.35, 2.40],
            "NPHI": [0.20, 0.30],
            "RT": [10.0, 10.0],
        }
    )

    sandstone_results, _ = _run_worker(_model_for_matrix(data, -0.02))
    limestone_results, _ = _run_worker(_model_for_matrix(data, 0.0))

    np.testing.assert_allclose(sandstone_results["PHIN"], [0.22, 0.32])
    np.testing.assert_allclose(limestone_results["PHIN"], [0.20, 0.30])
    assert not np.allclose(sandstone_results["PHIN"], limestone_results["PHIN"])


def test_las_failure_dialog_uses_sanitized_last_error_and_logs_detail(
    main_window, monkeypatch, caplog, tmp_path
):
    import ui.main_window as main_module

    class BrokenParser:
        data = None
        last_error = "curve section missing; token=secret-value\nTraceback: hidden"

        def read_las_from_buffer(self, _buffer):
            return False

    messages = []
    monkeypatch.setattr(main_module, "LASParser", BrokenParser)
    monkeypatch.setattr(
        main_module.QMessageBox,
        "critical",
        lambda _parent, title, text: messages.append((title, text)),
    )
    path = tmp_path / "broken.las"
    path.write_text("not a LAS", encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        main_window._load_single_las(str(path))

    assert messages
    assert "curve section missing" in messages[0][1]
    assert "secret-value" not in messages[0][1]
    assert "Traceback" not in messages[0][1]
    assert "secret-value" in caplog.text


def test_tops_failure_dialog_uses_actionable_last_error_and_logs_detail(
    main_window, monkeypatch, caplog, tmp_path
):
    import ui.main_window as main_module

    class BrokenTops:
        last_error = "missing required top column (path=/private/source.tops)"

        def read_tops_from_buffer(self, _buffer):
            return False

    messages = []
    monkeypatch.setattr(main_module, "FormationTops", BrokenTops)
    monkeypatch.setattr(
        main_module.QMessageBox,
        "warning",
        lambda _parent, title, text: messages.append((title, text)),
    )
    path = tmp_path / "broken.tops"
    path.write_text("not tops", encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        main_window._on_tops_file_selected(str(path))

    assert messages
    assert "missing required top column" in messages[0][1]
    assert "/private/source.tops" not in messages[0][1]
    assert "missing required top column" in caplog.text


def test_configure_logging_creates_one_rotating_handler_and_writes_detail(tmp_path):
    from services.logging_setup import configure_logging

    root = logging.getLogger()
    original_level = root.level
    handler = configure_logging(tmp_path)
    assert handler is not None

    logger = logging.getLogger("followup.logging")
    logger.error("packaged detail %s", "visible")
    handler.flush()

    log_path = tmp_path / "petrophyter.log"
    assert log_path.exists()
    assert "packaged detail visible" in log_path.read_text(encoding="utf-8")
    assert configure_logging(tmp_path) is handler
    assert sum(
        getattr(item, "_petrophyter_log_handler", False) for item in root.handlers
    ) == 1

    root.removeHandler(handler)
    handler.close()
    root.setLevel(original_level)


@pytest.mark.parametrize(
    "method_name",
    [
        "calculate_sw_archie",
        "calculate_sw_indonesian",
        "calculate_sw_simandoux",
        "calculate_sw_waxman_smits",
        "calculate_sw_dual_water",
    ],
)
@pytest.mark.parametrize(
    "parameter, invalid_value",
    [("rw", 0.0), ("a", np.nan), ("m", np.inf), ("n", -1.0)],
)
def test_saturation_methods_reject_invalid_archie_parameters(
    method_name, parameter, invalid_value
):
    calc = PetrophysicsCalculator(pd.DataFrame({"RT": [10.0]}))
    kwargs = {
        "phie": pd.Series([0.2]),
        "rw": 0.05,
        "a": 0.62,
        "m": 2.15,
        "n": 2.0,
    }
    if method_name in {"calculate_sw_indonesian", "calculate_sw_simandoux"}:
        kwargs["vsh"] = pd.Series([0.2])
    kwargs[parameter] = invalid_value

    with pytest.raises(ValueError, match=parameter):
        getattr(calc, method_name)("RT", **kwargs)


def test_saturation_rejects_nonpositive_or_infinite_rt_but_preserves_missing_nan():
    invalid_calc = PetrophysicsCalculator(pd.DataFrame({"RT": [10.0, 0.0, np.inf]}))
    with pytest.raises(ValueError, match="rt"):
        invalid_calc.calculate_sw_archie("RT", phie=pd.Series([0.2, 0.2, 0.2]))

    missing_calc = PetrophysicsCalculator(pd.DataFrame({"RT": [10.0, np.nan]}))
    result = missing_calc.calculate_sw_archie(
        "RT", phie=pd.Series([0.2, 0.2])
    )
    assert np.isfinite(result.iloc[0])
    assert np.isnan(result.iloc[1])


def test_gas_correction_rejects_formula_breaking_factor_boundaries():
    calc = PetrophysicsCalculator(
        pd.DataFrame({"RHOB": [2.1], "NPHI": [0.05]})
    )
    calc.calculate_porosity_density("RHOB")
    calc.calculate_porosity_neutron("NPHI")

    for parameter in ("gas_nphi_factor", "gas_rhob_factor"):
        with pytest.raises(ValueError, match=parameter):
            calc.calculate_phie_gas_corrected(**{parameter: 1.0})
        with pytest.raises(ValueError, match=parameter):
            calc.calculate_phie_gas_corrected(**{parameter: -0.01})


def test_analysis_summary_propagates_nonzero_solver_diagnostics():
    data = pd.DataFrame(
        {
            "DEPTH": [1000.0, 1001.0],
            "GR": [30.0, 90.0],
            "RHOB": [2.35, 2.40],
            "NPHI": [0.20, 0.30],
            "RT": [1.0e-9, 1.0e-9],
        }
    )
    model = _model_for_matrix(data, -0.02)
    model.sw_methods = ["Waxman-Smits", "Dual-Water"]
    model.sw_primary_method = "Waxman-Smits"

    _results, summary = _run_worker(model)

    assert summary["solver_diagnostics"]["SW_WS"]["no_root"] == 2
    assert summary["solver_diagnostics"]["SW_DW"]["no_root"] == 2
    assert any("SW_WS" in warning for warning in summary["warnings"])
    assert any("no-root" in warning for warning in summary["warnings"])


@pytest.mark.parametrize("depth_column", ["DEPTH", "DEPT", "MD"])
def test_qc_gap_detection_uses_same_depth_mnemonics_as_run_qc(depth_column):
    data = pd.DataFrame(
        {
            depth_column: [100.0, 101.0, 102.0, 103.0],
            "GR": [50.0, np.nan, np.nan, 60.0],
        }
    )
    report = QCModule(data).run_qc()
    assert report.depth_range == (100.0, 103.0)
    assert QCModule(data).get_data_gaps("GR", min_gap_size=2) == [(101.0, 102.0)]


def test_qc_missing_depth_has_explicit_run_error_and_no_gap_result():
    data = pd.DataFrame({"GR": [50.0, np.nan]})
    qc = QCModule(data)

    with pytest.raises(ValueError, match="explicit numeric depth"):
        qc.run_qc()
    assert qc.get_data_gaps("GR") == []


def test_export_merged_las_roundtrips_strict_metadata_and_safe_names(tmp_path):
    data = pd.DataFrame(
        {
            "DEPTH": [1001.0, 1000.0],
            "GR": [50.0, np.nan],
            "A B": [1.2, 2.3],
            "A-B": [3.4, 4.5],
        }
    )
    output = tmp_path / "strict.las"

    export_merged_las(data, {"well_name": "WELL:17"}, str(output))
    parsed = lasio.read(str(output))

    assert [curve.mnemonic for curve in parsed.curves] == [
        "DEPTH",
        "GR",
        "A_B",
        "A_B_2",
    ]
    assert [curve.unit for curve in parsed.curves] == [
        "FT",
        "API",
        "UNITLESS",
        "UNITLESS",
    ]
    assert parsed.well["WELL"].value == "WELL_17"
    np.testing.assert_allclose(parsed["DEPTH"], [1000.0, 1001.0])
    assert np.isnan(parsed["GR"][0])
    assert parsed["GR"][1] == pytest.approx(50.0)
    np.testing.assert_allclose(parsed["A_B"], [2.3, 1.2])
    np.testing.assert_allclose(parsed["A_B_2"], [4.5, 3.4])


def test_diagnostics_tab_shows_solver_counts_only_when_nonzero(qtbot):
    from ui.tabs.diagnostics_tab import DiagnosticsTab

    model = AppModel()
    model._calculated = True
    model._results = pd.DataFrame(
        {"SW_WS": [1.0], "SW_DW": [1.0]}
    )
    model._summary = {
        "solver_diagnostics": {
            "SW_WS": {"no_root": 2, "failed": 1},
            "SW_DW": {"no_root": 0, "failed": 0},
        }
    }
    tab = DiagnosticsTab(model)
    qtbot.addWidget(tab)

    tab.update_display()

    assert "SW_WS" in tab.sw_warnings.text()
    assert "2 no-root" in tab.sw_warnings.text()
    assert "1 failed" in tab.sw_warnings.text()
    assert "SW_DW" not in tab.sw_warnings.text()

    model._summary = {
        "solver_diagnostics": {
            "SW_WS": {"no_root": 0, "failed": 0},
            "SW_DW": {"no_root": 0, "failed": 0},
        }
    }
    tab.update_display()
    assert tab.sw_warnings.text() == ""
