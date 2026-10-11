"""Changes since the last run and Revert to last run (P0-UI/UX U12)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from models.app_model import AppModel
from models.project import WellDataset
from modules import param_scopes as ps
from modules.param_diff import describe, param_changes, summary_text
from tests.golden.cases import FULL_MAPPING, fixture_frame, make_tops


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")

    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


def _params(**over):
    base = {"rw": 0.05, "m": 2.0, "sw_methods": ["Archie"], "param_info": {"rw": {}},
            "curve_mapping": {"GR": "GR", "RT": "RT"}, "zone_plan": {}}
    base.update(over)
    return base


# ---- param_diff -------------------------------------------------------------------
def test_well_value_and_list_changes():
    changes = param_changes(_params(), _params(rw=0.06, sw_methods=["Archie", "Simandoux"]))
    assert [describe(c) for c in changes] == [
        "rw: 0.05 → 0.06", "sw_methods: Archie → Archie, Simandoux"]
    assert all(c["revertible"] for c in changes)
    assert param_changes(_params(), _params(rw=0.05 + 1e-15)) == []


def test_zone_following_the_well_is_not_repeated():
    old_plan = {"UPPER": {"params": {**_params(), "m": 2.15}}}
    new_plan = {"UPPER": {"params": {**_params(rw=0.06), "m": 2.15}}}
    changes = param_changes(_params(zone_plan=old_plan), _params(rw=0.06, zone_plan=new_plan))
    assert [describe(c) for c in changes] == ["rw: 0.05 → 0.06"]


def test_zone_own_change_and_zone_entry_removed():
    old_plan = {"UPPER": {"params": {**_params(), "m": 2.15}}}
    changes = param_changes(_params(zone_plan=old_plan), _params())   # zone entry cleared
    assert [describe(c) for c in changes] == ["UPPER · m: 2.15 → 2"]


def test_curve_mapping_conditional_keys_and_tops():
    old = _params()
    new = _params(curve_mapping={"GR": "CGR", "RT": "RT"}, shale_min_points=50)
    changes = param_changes(old, new, [("A", 1.0, 2.0)], [("A", 1.0, 2.5)])
    lines = [describe(c) for c in changes]
    assert lines == ["shale_min_points: not set → 50", "GR curve: GR → CGR",
                     "Formation tops changed (Revert does not restore tops)"]
    assert [c["revertible"] for c in changes] == [True, True, False]
    assert summary_text(changes) == (
        "3 changes since the last run: shale_min_points: not set → 50; GR curve: GR → CGR (+1 more)")
    assert summary_text([]) is None


# ---- model state ------------------------------------------------------------------
def _model():
    model = AppModel()
    for name in ("A", "B"):
        ds = WellDataset(key=f"WELL:{name}", display_name=name)
        ds.las_data = fixture_frame("sample_log_data")
        ds.curve_mapping = dict(FULL_MAPPING)
        ds.formation_tops = make_tops()
        model.add_well(ds)
    model.set_active_well("WELL:A")
    return model


def test_restore_param_state_gives_back_the_hash():
    model = _model()
    a, b = model.project.get("WELL:A"), model.project.get("WELL:B")
    before = model.param_state(a)
    hash_a, hash_b = model.well_params_hash(a), model.well_params_hash(b)
    zone = model.zones_for(a)[0]

    model.rw = 0.2
    model.m = 2.3
    model.set_entry("a", ps.MANUAL, 0.81, scope="well", well=a)
    model.set_entry("n", ps.MANUAL, 2.4, scope="project", zone=zone)
    model.set_curve_mapping("GR", "None")
    a.analysis_mode = "Per-Formation"
    assert model.well_params_hash(a) != hash_a and model.well_params_hash(b) != hash_b
    assert model.project_state_differs(before)

    seen = []
    model.parameters_changed.connect(lambda: seen.append("p"))
    model.scoped_params_changed.connect(lambda key: seen.append(key))
    model.restore_param_state(a, before)
    assert model.well_params_hash(a) == hash_a
    assert model.well_params_hash(b) == hash_b       # project values are shared
    assert seen == ["p", "WELL:A"]
    assert not model.project_state_differs(before)


def test_restoring_another_well_leaves_the_active_well_alone():
    model = _model()
    a, b = model.project.get("WELL:A"), model.project.get("WELL:B")
    state_b = model.param_state(b)
    a.analysis_mode = "Per-Formation"
    model.restore_param_state(b, state_b)
    assert a.analysis_mode == "Per-Formation"


# ---- window ----------------------------------------------------------------------
@pytest.fixture
def window(qtbot):
    from ui.main_window import MainWindow

    widget = MainWindow()
    qtbot.addWidget(widget)
    yield widget
    widget.close()


def _run_all(window, qtbot):
    window.actions_["run_all"].trigger()
    qtbot.waitUntil(lambda: not window.batch_runner.is_running(), timeout=60000)
    qtbot.wait(50)


def test_footer_lists_changes_and_revert_restores_the_last_run(window, qtbot, monkeypatch):
    model = window.model
    for name in ("A", "B"):
        ds = WellDataset(key=f"WELL:{name}", display_name=name)
        ds.las_data = fixture_frame("sample_log_data")
        ds.curve_mapping = dict(FULL_MAPPING)
        model.project.add_well(ds)
    model.set_active_well("WELL:A")
    pw = window.params_window
    a = model.project.get("WELL:A")
    assert not pw.changes_label.isVisibleTo(pw) and not pw.revert_btn.isVisibleTo(pw)

    _run_all(window, qtbot)
    assert a.last_run is not None and not a.stale
    assert pw.changes_label.text() == "No changes since the last run"
    assert pw.revert_btn.isVisibleTo(pw) and not pw.revert_btn.isEnabled()

    old_m = model.m
    pw.archie_params_widget.m_spin.setValue(old_m + 0.25)
    assert a.stale
    assert pw.changes_label.text().startswith("1 change since the last run: m:")
    assert pw.revert_btn.isEnabled()
    assert "m:" in window.stale_label.toolTip()

    asked = []
    monkeypatch.setattr(pw, "_confirm_revert",
                        lambda lines, shared: asked.append((lines, shared)) or True)
    pw.revert_btn.click()
    assert asked and asked[0][1] is True                # m is a project value
    assert model.m == pytest.approx(old_m)
    assert pw.archie_params_widget.m_spin.value() == pytest.approx(old_m)
    assert model.well_params_hash(a) == a.run_params_hash and not a.stale
    assert pw.changes_label.text() == "No changes since the last run"


def test_cancelled_revert_changes_nothing(window, qtbot, monkeypatch):
    model = window.model
    ds = WellDataset(key="WELL:A", display_name="A")
    ds.las_data = fixture_frame("sample_log_data")
    ds.curve_mapping = dict(FULL_MAPPING)
    model.project.add_well(ds)
    model.set_active_well("WELL:A")
    _run_all(window, qtbot)
    pw = window.params_window
    pw.archie_params_widget.m_spin.setValue(model.m + 0.25)
    changed = model.m
    monkeypatch.setattr(pw, "_confirm_revert", lambda lines, shared: False)
    pw.revert_btn.click()
    assert model.m == changed and ds.stale
