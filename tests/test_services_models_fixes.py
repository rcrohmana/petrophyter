"""Behavioral regressions for service/model correctness fixes."""

import io
import json
import logging

import numpy as np
import pandas as pd
import pytest

from models.app_model import AppModel
from modules.petrophysics import PetrophysicsCalculator
from services.analysis_service import AnalysisService, AnalysisWorker
from services.export_service import ExportService
from services.merge_service import MergeWorker
from services.session_service import SessionService


class TestAnalysisServiceFixes:
    @staticmethod
    def _analysis_model(data, **mapping):
        model = AppModel()
        model.las_data = data
        model.curve_mapping = {
            "GR": mapping.get("GR", "GR"),
            "RHOB": mapping.get("RHOB", "RHOB"),
            "NPHI": mapping.get("NPHI", "NPHI"),
            "DT": mapping.get("DT", "DT"),
            "RT": mapping.get("RT", "RT"),
        }
        return model

    def test_quantile_shale_mode_returns_statistical_result(self):
        rng = np.random.default_rng(42)
        n = 200
        data = pd.DataFrame(
            {
                "DEPTH": np.linspace(1000, 1200, n),
                "GR": np.r_[rng.normal(30, 5, n // 2), rng.normal(120, 10, n // 2)],
                "RHOB": np.r_[
                    rng.normal(2.25, 0.03, n // 2),
                    rng.normal(2.55, 0.04, n // 2),
                ],
                "NPHI": np.r_[
                    rng.normal(0.18, 0.02, n // 2),
                    rng.normal(0.38, 0.03, n // 2),
                ],
                "DT": np.r_[
                    rng.normal(78, 3, n // 2), rng.normal(100, 5, n // 2)
                ],
            }
        )
        model = self._analysis_model(data, RT="None")
        model.shale_selection_mode = "quantile"
        model.shale_vsh_quantile = 0.90
        model.shale_min_points = 10
        model.vsh_baseline_method = "Statistically (Auto)"
        model.vsh_methods = ["Linear"]

        result = AnalysisService().calculate_shale_parameters(model)

        assert result is not None
        assert result.get("method") == "statistical_vsh"
        assert result.get("shale_selection_mode") == "quantile"

    def test_rw_estimation_uses_mapped_nphi_proxy(self, monkeypatch):
        data = pd.DataFrame(
            {
                "DEPTH": [1000.0, 1001.0],
                "NPHI_ACTUAL": [0.25, 0.30],
                "RT_ACTUAL": [2.0, 3.0],
            }
        )
        model = self._analysis_model(
            data, GR="None", RHOB="None", NPHI="NPHI_ACTUAL", DT="None", RT="RT_ACTUAL"
        )
        seen = []

        class SpyStatistics:
            def __init__(self, _data):
                pass

            def estimate_rw_from_rt_water_zone(
                self, rt_curve, phi_curve, porosity_threshold, a, m
            ):
                seen.append((rt_curve, phi_curve))
                return 0.12

            def estimate_rsh(self, *args):
                return 5.0

        monkeypatch.setattr("services.analysis_service.StatisticsUtils", SpyStatistics)
        model.rw = 0.01

        result = AnalysisService().calculate_rw_rsh(model)

        assert result == {"rw": 0.12, "rsh": 5.0}
        assert seen == [("RT_ACTUAL", "NPHI_ACTUAL")]

    def test_worker_rw_estimation_uses_nphi_proxy(self, monkeypatch):
        n = 20
        data = pd.DataFrame(
            {
                "DEPTH": np.arange(1000.0, 1000.0 + n),
                "GR": np.linspace(30.0, 80.0, n),
                "RHOB": np.full(n, 2.35),
                "NPHI": np.full(n, 0.25),
                "RT": np.full(n, 3.0),
            }
        )
        model = self._analysis_model(data, DT="None")
        model.rw = 0.01
        seen = []

        class SpyStatistics:
            def __init__(self, _data):
                pass

            def estimate_gr_baseline(self, curve):
                return 20.0, 100.0

            def estimate_rw_from_rt_water_zone(self, rt_curve, phi_curve, *args):
                seen.append(phi_curve)
                return 0.12

            def estimate_rsh(self, *args):
                return 5.0

        monkeypatch.setattr("services.analysis_service.StatisticsUtils", SpyStatistics)
        errors = []
        worker = AnalysisWorker(model)
        worker.signals.error.connect(errors.append)

        worker.run()

        assert errors == []
        assert seen == ["NPHI"]

    def test_worker_emits_clear_error_when_las_data_is_none(self):
        worker = AnalysisWorker(AppModel())
        errors = []
        worker.signals.error.connect(errors.append)

        worker.run()

        assert len(errors) == 1
        assert "no data" in errors[0].lower()

    def test_worker_skips_phit_without_porosity_curves(self, monkeypatch):
        data = pd.DataFrame(
            {
                "DEPTH": np.arange(1000.0, 1010.0),
                "GR": np.linspace(30.0, 80.0, 10),
                "RT": np.linspace(2.0, 5.0, 10),
            }
        )
        model = self._analysis_model(
            data, RHOB="None", NPHI="None", DT="None"
        )
        model.sw_methods = ["Unknown saturation method"]
        called = []

        def fail_if_called(self, *args, **kwargs):
            called.append(True)
            raise AssertionError("PHIT should not be calculated without porosity curves")

        monkeypatch.setattr(
            PetrophysicsCalculator,
            "calculate_phit_neutron_density",
            fail_if_called,
        )
        errors = []
        completed = []
        worker = AnalysisWorker(model)
        worker.signals.error.connect(errors.append)
        worker.signals.completed.connect(
            lambda results, summary: completed.append((results, summary))
        )

        worker.run()

        assert called == []
        assert errors == []
        assert len(completed) == 1
        assert "PHIT" not in completed[0][0].columns
        assert any("PHIT" in warning for warning in completed[0][1]["warnings"])
        assert any("PHIE" in warning for warning in completed[0][1]["warnings"])
        assert any("selected method" in warning for warning in completed[0][1]["warnings"])

    def test_unknown_vsh_method_falls_back_to_linear(self):
        n = 20
        data = pd.DataFrame(
            {
                "DEPTH": np.arange(1000.0, 1000.0 + n),
                "GR": np.linspace(30.0, 120.0, n),
                "RHOB": np.full(n, 2.35),
                "NPHI": np.full(n, 0.22),
                "RT": np.full(n, 5.0),
            }
        )
        model = self._analysis_model(data, DT="None")
        model.vsh_methods = ["Not a VSH method"]
        errors = []
        completed = []
        worker = AnalysisWorker(model)
        worker.signals.error.connect(errors.append)
        worker.signals.completed.connect(lambda results, summary: completed.append(results))

        worker.run()

        assert errors == []
        assert len(completed) == 1
        assert "VSH" in completed[0].columns


class TestMergeServiceFixes:
    def test_worker_snapshots_parser_and_filename_lists(self):
        parsers = [object(), object()]
        names = ["a.las", "b.las"]
        worker = MergeWorker(parsers, names, 0.5, 5.0)

        parsers.clear()
        names.append("c.las")

        assert len(worker.parsers) == 2
        assert worker.file_names == ["a.las", "b.las"]

    def test_worker_surfaces_cross_well_warning(self, monkeypatch):
        class FakeHandler:
            def merge_las_files(self, *args, **kwargs):
                return {
                    "merged_df": pd.DataFrame({"DEPTH": [1000.0]}),
                    "merge_report": object(),
                }

        monkeypatch.setattr(
            "services.merge_service.validate_same_well",
            lambda parsers: (False, ["Well A", "Well B"]),
        )
        monkeypatch.setattr("services.merge_service.LASHandler", FakeHandler)
        messages = []
        completed = []
        worker = MergeWorker([object(), object()], ["a", "b"], 0.5, 5.0)
        worker.signals.progress.connect(lambda message, percent: messages.append(message))
        worker.signals.completed.connect(lambda df, report: completed.append(df))

        worker.run()

        assert any("warning" in message.lower() and "different wells" in message.lower() for message in messages)
        assert len(completed) == 1

    @pytest.mark.parametrize(
        ("step_ft", "gap_limit_ft", "expected"),
        [(0, 5.0, "step"), (0.5, -1, "gap")],
    )
    def test_worker_rejects_invalid_merge_limits(self, monkeypatch, step_ft, gap_limit_ft, expected):
        class FailIfCalled:
            def merge_las_files(self, *args, **kwargs):
                raise AssertionError("merge should not start")

        monkeypatch.setattr("services.merge_service.LASHandler", FailIfCalled)
        errors = []
        worker = MergeWorker([object(), object()], ["a", "b"], step_ft, gap_limit_ft)
        worker.signals.error.connect(errors.append)

        worker.run()

        assert len(errors) == 1
        assert expected in errors[0].lower()

    def test_worker_rejects_empty_merge_result(self, monkeypatch):
        class EmptyHandler:
            def merge_las_files(self, *args, **kwargs):
                return {"merged_df": pd.DataFrame(), "merge_report": object()}

        monkeypatch.setattr("services.merge_service.LASHandler", EmptyHandler)
        errors = []
        completed = []
        worker = MergeWorker([object(), object()], ["a", "b"], 0.5, 5.0)
        worker.signals.error.connect(errors.append)
        worker.signals.completed.connect(lambda df, report: completed.append(df))

        worker.run()

        assert len(errors) == 1
        assert "empty" in errors[0].lower()
        assert completed == []


class TestExportServiceFixes:
    @staticmethod
    def _results():
        return pd.DataFrame({"DEPTH": [1000.0, 1001.0], "GR": [30.0, 40.0]})

    @staticmethod
    def _summary():
        return {
            "selected_formations": ["Sand", "Shale"],
            "nested": {"limits": [0.1, 0.2]},
            "net_pay": 1.5,
        }

    def test_excel_export_serializes_list_and_nested_summary(self, tmp_path):
        path = tmp_path / "summary.xlsx"

        assert ExportService().export_excel(self._results(), self._summary(), str(path))

        summary = pd.read_excel(path, sheet_name="Summary")
        values = dict(zip(summary["Parameter"], summary["Value"]))
        assert json.loads(values["selected_formations"]) == ["Sand", "Shale"]
        assert json.loads(values["nested"]) == {"limits": [0.1, 0.2]}

    def test_excel_buffer_uses_same_summary_serialization(self):
        payload = ExportService().get_excel_bytes(self._results(), self._summary())

        summary = pd.read_excel(io.BytesIO(payload), sheet_name="Summary")
        values = dict(zip(summary["Parameter"], summary["Value"]))
        assert json.loads(values["selected_formations"]) == ["Sand", "Shale"]
        assert json.loads(values["nested"]) == {"limits": [0.1, 0.2]}

    def test_las_export_writes_utf8_well_name(self, tmp_path):
        path = tmp_path / "merged.las"
        well_name = "Møller井"

        assert ExportService().export_las(
            self._results(), {"well_name": well_name}, str(path)
        )

        assert well_name in path.read_text(encoding="utf-8")

    def test_csv_failure_preserves_existing_file(self, monkeypatch, tmp_path):
        path = tmp_path / "results.csv"
        path.write_text("original\n", encoding="utf-8")

        def fail_after_partial_write(self, file_path, *args, **kwargs):
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write("partial\n")
            raise RuntimeError("simulated write failure")

        monkeypatch.setattr(pd.DataFrame, "to_csv", fail_after_partial_write)
        errors = []
        service = ExportService()
        service.export_error.connect(errors.append)

        assert service.export_csv(self._results(), str(path)) is False
        assert path.read_text(encoding="utf-8") == "original\n"
        assert errors and "CSV export failed" in errors[0]

    def test_permission_error_has_actionable_message(self, monkeypatch, tmp_path):
        def deny_replace(*args, **kwargs):
            raise PermissionError("locked")

        monkeypatch.setattr("services.export_service.os.replace", deny_replace)
        errors = []
        service = ExportService()
        service.export_error.connect(errors.append)

        assert service.export_csv(self._results(), str(tmp_path / "results.csv")) is False
        assert errors and "close" in errors[0].lower()

    def test_export_rejects_missing_results(self, tmp_path):
        errors = []
        service = ExportService()
        service.export_error.connect(errors.append)

        assert service.export_csv(None, str(tmp_path / "results.csv")) is False
        assert errors and "results" in errors[0].lower()


class TestSessionAndModelFixes:
    def test_app_model_round_trips_new_session_fields(self, tmp_path):
        service = SessionService()
        model = AppModel()
        model.las_filename = "well-a.las"
        model.curve_mapping = {"GR": "GRC", "NPHI": "NPHI_A"}
        model.primary_phie_method = "PHIE_N"
        model.shale_vsh_threshold = 0.73
        model.shale_gate_logs = False
        model.shale_iqr_filter = False
        model.shale_selection_mode = "quantile"
        model.shale_vsh_quantile = 0.88
        model.shale_min_points = 23
        model.shale_sweep_tmin = 0.61
        model.shale_sweep_tmax = 0.91
        model.shale_sweep_step = 0.03
        model.sw_methods = ["Archie", "Simandoux"]
        model.sw_primary_method = "Archie"
        model.ws_qv = 0.4
        model.ws_b = 1.2
        model.dw_swb = 0.15
        model.dw_rwb = 0.25

        path = tmp_path / "session.json"
        assert service.save_session(model, str(path))
        restored = AppModel()
        assert service.apply_session_to_model(restored, service.load_session(str(path)))
        assert restored.las_filename == "well-a.las"

        for field in (
            "curve_mapping", "primary_phie_method", "shale_vsh_threshold",
            "shale_gate_logs", "shale_iqr_filter", "shale_selection_mode",
            "shale_vsh_quantile", "shale_min_points", "shale_sweep_tmin",
            "shale_sweep_tmax", "shale_sweep_step", "sw_methods",
            "sw_primary_method", "ws_qv", "ws_b", "dw_swb", "dw_rwb",
        ):
            assert getattr(restored, field) == getattr(model, field)

    def test_missing_optional_model_fields_do_not_abort_save(self, tmp_path):
        class MinimalModel:
            las_filename = "minimal.las"

        path = tmp_path / "minimal.json"
        assert SessionService().save_session(MinimalModel(), str(path))

    def test_session_version_mismatch_is_logged_but_loads(self, caplog, tmp_path):
        path = tmp_path / "old.json"
        path.write_text(json.dumps({"_session_version": "0.9", "rw": 0.1}), encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            data = SessionService().load_session(str(path))

        assert data["rw"] == 0.1
        assert "version" in caplog.text.lower()

    def test_session_write_failure_preserves_existing_file(self, tmp_path):
        model = AppModel()
        model.selected_formations = [object()]
        path = tmp_path / "session.json"
        path.write_text("original", encoding="utf-8")

        assert SessionService().save_session(model, str(path)) is False
        assert path.read_text(encoding="utf-8") == "original"

    def test_app_model_reset_clears_all_derived_fields_but_keeps_parameters(self):
        model = AppModel()
        model.rho_matrix = 2.71
        model.calculated_shale = {"rho_shale": 2.5}
        model.shale_method_used = "statistical"
        model.calculated_rw = 0.12
        model.calculated_rsh = 6.0
        model.calculated_C = 100.0
        model.calculated_P = 4.0
        model.calculated_Q = 2.0
        model.results = pd.DataFrame({"PHIE": [0.2]})
        model.summary = {"net_pay": 1.0}

        model.reset()

        assert model.rho_matrix == 2.71
        assert model.calculated_shale is None
        assert model.shale_method_used == "custom"
        assert model.calculated_rw is None
        assert model.calculated_rsh is None
        assert model.calculated_C is None
        assert model.calculated_P is None
        assert model.calculated_Q is None
        assert model.results is None
        assert model.summary is None

    def test_app_model_new_data_clears_derived_state(self):
        model = AppModel()
        model.results = pd.DataFrame({"PHIE": [0.2]})
        model.calculated_shale = {"rho_shale": 2.5}
        model.shale_method_used = "statistical"

        model.las_data = pd.DataFrame({"DEPTH": [1000.0]})

        assert model.results is None
        assert model.calculated_shale is None
        assert model.shale_method_used == "custom"

    def test_set_analysis_results_updates_summary_and_emits_once(self):
        model = AppModel()
        emitted = []
        model.analysis_complete.connect(lambda: emitted.append(True))
        results = pd.DataFrame({"PHIE": [0.2]})
        summary = {"net_pay": 1.0}

        model.set_analysis_results(results, summary)

        assert model.results is results
        assert model.summary is summary
        assert model.calculated is True
        assert emitted == [True]
