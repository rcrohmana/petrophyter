"""Multi-well import wiring: menu actions, routing of well-column files, atomic apply (spec 3.9)."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QDialog, QFileDialog

from tests.test_multiwell_loading import _write
from ui.main_window import MainWindow
from ui.widgets.well_import_dialog import MultiWellImportDialog

ACCEPTED = QDialog.DialogCode.Accepted
REJECTED = QDialog.DialogCode.Rejected


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A modal box would block the offscreen test run; fail loudly instead."""
    from PyQt6.QtWidgets import QMessageBox

    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")

    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


@pytest.fixture
def window(qtbot):
    widget = MainWindow()
    qtbot.addWidget(widget)
    yield widget
    widget.close()


@pytest.fixture
def three_wells(window, tmp_path):
    """BKS-01, BKS-02, BKS-03 (active)."""
    for name, well in (("a.las", "BKS-01"), ("b.las", "BKS-02"), ("c.las", "BKS-03")):
        window._load_single_las(_write(tmp_path, name, well=well))
    return window


@pytest.fixture
def dialogs(monkeypatch):
    """Replace ``MultiWellImportDialog.exec``: records the dialog, optionally edits, then answers."""
    seen = []
    state = {"result": ACCEPTED, "edit": None}

    def fake_exec(self):
        seen.append(self)
        if state["edit"]:
            state["edit"](self)
        return state["result"]

    monkeypatch.setattr(MultiWellImportDialog, "exec", fake_exec)
    return type("Dialogs", (), {"seen": seen, "state": state})


def key(window, name):
    return next(ds.key for ds in window.model.project.wells if ds.display_name == name)


def well(window, name):
    return window.model.project.get(key(window, name))


def tops_file(tmp_path, text=None, name="tops.csv"):
    path = tmp_path / name
    path.write_text(text or (
        "Well,Formation,Top (ft),Bottom (ft)\n"
        "BKS-01,Upper,1005,1030\nBKS-01,Lower,1030,1055\n"
        "BKS-02,Upper,1010,1040\nBKS-03,Upper,1000,1020\nXYZ-9,Upper,1000,1020\n"))
    return str(path)


def set_clean(window):
    """Mark every well as run with its current parameters (so a change shows as stale)."""
    for ds in window.model.project.wells:
        ds.calculated = True
        ds.run_params_hash = window.model.well_params_hash(ds)
        ds.stale = False


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------
def test_multi_well_actions_need_a_loaded_well(window, tmp_path):
    for name in ("open_tops_multi", "open_core_multi"):
        assert not window.actions_[name].isEnabled()
    window._load_single_las(_write(tmp_path, "a.las", well="BKS-01"))
    for name in ("open_tops_multi", "open_core_multi"):
        assert window.actions_[name].isEnabled()
    labels = [a.text() for a in window._menus["file"].actions()]
    assert "Open Formation Tops (Multi-Well)…" in labels
    assert "Open Core Data (Multi-Well)…" in labels


def test_well_context_menu_offers_the_multi_well_actions(three_wells):
    browser = three_wells.data_browser
    root = browser.tree.model().index(0, 0)
    menu = browser._build_menu(root)
    texts = [a.text() for a in menu.actions()]
    assert "Open Formation Tops (Multi-Well)…" in texts
    assert "Open Core Data (Multi-Well)…" in texts


def test_menu_action_opens_the_dialog_and_assigns(three_wells, tmp_path, monkeypatch, dialogs):
    path = tops_file(tmp_path)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (path, "")))
    three_wells.actions_["open_tops_multi"].trigger()
    assert len(dialogs.seen) == 1 and dialogs.seen[0].kind == "tops"
    assert [fm.name for fm in well(three_wells, "BKS-01").formation_tops.formations] == ["Upper", "Lower"]


def test_multi_well_action_on_a_file_without_a_well_column_says_so(three_wells, tmp_path, dialogs):
    path = tmp_path / "plain.txt"
    path.write_text("Formation\tTop (ft)\tBottom (ft)\nA\t1000\t1050\n")
    three_wells._import_multi_well("tops", str(path))
    assert not dialogs.seen
    assert "no well column" in three_wells.banner.message_label.text()
    assert all(ds.formation_tops is None for ds in three_wells.model.project.wells)


# ---------------------------------------------------------------------------
# Routing of the single-well loaders (decision D3)
# ---------------------------------------------------------------------------
def test_single_well_loader_routes_a_well_column_file_to_the_dialog(three_wells, tmp_path, dialogs):
    three_wells._on_tops_file_selected(tops_file(tmp_path))
    assert len(dialogs.seen) == 1
    assert [fm.name for fm in well(three_wells, "BKS-01").formation_tops.formations] == ["Upper", "Lower"]
    assert three_wells.model.active_well.display_name == "BKS-03"
    assert [fm.name for fm in three_wells.model.formation_tops.formations] == ["Upper"]


def test_rejecting_the_routed_dialog_changes_nothing(three_wells, tmp_path, dialogs):
    dialogs.state["result"] = REJECTED
    three_wells._on_tops_file_selected(tops_file(tmp_path))
    assert len(dialogs.seen) == 1
    assert all(ds.formation_tops is None and ds.tops_path is None
               for ds in three_wells.model.project.wells)
    assert not three_wells.banner.isVisible()


def test_single_well_core_loader_routes_a_well_column_file(three_wells, tmp_path, dialogs):
    path = tmp_path / "core.csv"
    path.write_text("Well,Depth (ft),Porosity,Permeability\n"
                    "BKS-01,1010,0.20,15\nBKS-02,1015,0.18,8\n")
    three_wells._on_core_file_selected(str(path))
    assert len(dialogs.seen) == 1 and dialogs.seen[0].kind == "core"
    assert three_wells.model.core_data is None            # BKS-03 is not in the file
    assert len(well(three_wells, "BKS-01").core_data.data) == 1


def test_single_well_loader_extends_the_last_formation_to_the_log_bottom(three_wells, tmp_path, dialogs):
    path = tmp_path / "tops.txt"
    path.write_text("Formation\tTop (ft)\nA\t1005\nB\t1030\n")
    three_wells._on_tops_file_selected(str(path))
    assert not dialogs.seen
    last = three_wells.model.formation_tops.formations[-1]
    assert last.bottom_depth == pytest.approx(three_wells._log_depth_range()[1])
    assert last.bottom_depth > 1030
    assert three_wells.model.active_well.tops_import is None


def test_single_well_loader_reports_excluded_rows_in_the_banner(three_wells, tmp_path, dialogs):
    path = tmp_path / "tops.txt"
    path.write_text("Formation\tTop (ft)\tBottom (ft)\nA\t1005\t1020\nB\tabc\t1030\nC\t1030\t1050\n")
    three_wells._on_tops_file_selected(str(path))
    text = three_wells.banner.message_label.text()
    assert "1 row(s) excluded (line 3)" in text
    assert three_wells.banner.isVisible()


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
def test_apply_writes_only_the_chosen_wells(three_wells, tmp_path, dialogs):
    def skip_bks02(dialog):
        index = next(i for i, r in enumerate(dialog.plan.rows) if r.file_well == "BKS-02")
        dialog.plan.set_target(index, None)

    dialogs.state["edit"] = skip_bks02
    path = tops_file(tmp_path)
    three_wells._import_multi_well("tops", path)
    assert well(three_wells, "BKS-01").tops_path == path
    assert well(three_wells, "BKS-03").tops_path == path
    assert well(three_wells, "BKS-02").formation_tops is None
    assert well(three_wells, "BKS-02").tops_import is None
    record = well(three_wells, "BKS-01").tops_import
    assert record["file_well"] == "BKS-01" and record["depth_unit"] == "FT"
    assert record["columns"]["top"] == "Top (ft)"


def test_apply_fires_the_active_well_signals_and_tops_changed_once(three_wells, tmp_path, dialogs):
    window = three_wells
    loaded, changed, updated = [], [], []
    window.model.formation_tops_loaded.connect(lambda: loaded.append(1))
    window.model.project.tops_changed.connect(changed.append)
    window.model.project.well_updated.connect(updated.append)
    window._import_multi_well("tops", tops_file(tmp_path))
    assert len(loaded) == 1
    assert len(changed) == 1 and set(changed[0]) == {
        key(window, "BKS-01"), key(window, "BKS-02"), key(window, "BKS-03")}
    assert set(updated) >= set(changed[0])
    # The active well's panels point at its new tops.
    assert window.params_window.analysis_mode_widget.formation_list.count() == 1


def test_scope_widgets_follow_tops_changed(three_wells, tmp_path, dialogs):
    """Zones of a non-active well reach the zone combo and the Zones grid at Project scope."""
    window = three_wells
    path = tops_file(tmp_path, "Well,Formation,Top (ft),Bottom (ft)\nBKS-01,Alpha,1005,1030\n")
    bar, grid = window.params_window.scope_bar, window.params_window.zone_grid
    assert window.model.edit_scope == "project"
    assert "ALPHA" not in [bar.zone_combo.itemText(i) for i in range(bar.zone_combo.count())]
    window._import_multi_well("tops", path)
    assert window.model.active_well.display_name == "BKS-03"
    assert "ALPHA" in [bar.zone_combo.itemText(i) for i in range(bar.zone_combo.count())]
    assert "ALPHA" in [grid.table.item(r, 0).text() for r in range(grid.table.rowCount())]


def test_stale_is_recomputed_only_for_the_changed_wells(three_wells, tmp_path, dialogs, monkeypatch):
    window = three_wells
    set_clean(window)
    calls = []
    original = window._recompute_stale
    monkeypatch.setattr(window, "_recompute_stale", lambda keys=None: (calls.append(keys), original(keys)))
    path = tops_file(tmp_path, "Well,Formation,Top (ft),Bottom (ft)\nBKS-01,Upper,1005,1030\n")
    window._import_multi_well("tops", path)
    assert calls == [[key(window, "BKS-01")]]
    assert well(window, "BKS-01").stale
    assert not well(window, "BKS-02").stale and not well(window, "BKS-03").stale


def test_banner_counts_assigned_kept_skipped_and_wellless_rows(three_wells, tmp_path, dialogs):
    window = three_wells
    other = tmp_path / "other.txt"
    other.write_text("Formation\tTop (ft)\tBottom (ft)\nOld\t1000\t1050\n")
    from modules.formation_tops import FormationTops
    existing = FormationTops()
    existing.read_tops_file(str(other))
    first = well(window, "BKS-01")
    first.formation_tops, first.tops_path = existing, str(other)
    path = tops_file(tmp_path, (
        "Well,Formation,Top (ft),Bottom (ft)\n"
        "BKS-01,Upper,1005,1030\nBKS-02,Upper,1010,1040\nXYZ-9,Upper,1000,1020\n"
        ",Stray,900,950\n"))
    window._import_multi_well("tops", path)
    lines = window.banner.message_label.text().split("\n")
    assert lines[0] == ("Formation tops assigned to 1 well (1 kept existing, 1 skipped). "
                        "1 row without a well was excluded.")
    assert first.formation_tops is existing                      # Keep existing is the default
    assert [fm.name for fm in well(window, "BKS-02").formation_tops.formations] == ["Upper"]


def test_replace_overwrites_existing_tops_and_drops_missing_scope_formations(three_wells, tmp_path, dialogs):
    window = three_wells
    path = tops_file(tmp_path)
    first = well(window, "BKS-01")
    window._import_multi_well("tops", path)                    # first import: assign
    first.selected_formations = ["Lower", "Gone"]
    first.zone_overrides = {"GONE": {"a": {"mode": "manual", "value": 1.0}}}
    window._import_multi_well("tops", path)                    # same file again: replace by default
    assert first.selected_formations == ["Lower"]
    assert first.zone_overrides == {"GONE": {"a": {"mode": "manual", "value": 1.0}}}   # kept
    text = window.banner.message_label.text()
    assert "Gone removed from the analysis scope" in text
    assert "zone parameters for GONE" in text and "(kept)" in text


def test_a_failing_build_changes_nothing_and_shows_one_banner(three_wells, tmp_path, dialogs):
    path = tops_file(tmp_path, "Well,Formation,Top,Bottom\nBKS-01,Upper,1005,1030\n")  # no unit
    three_wells._import_multi_well("tops", path)
    assert all(ds.formation_tops is None for ds in three_wells.model.project.wells)
    assert three_wells.banner.message_label.text().startswith("Nothing was changed:")
    assert "depth unit" in three_wells.banner.message_label.text()


def test_core_apply_stores_feet_and_the_chosen_unit(three_wells, tmp_path, dialogs):
    window = three_wells
    loaded = []
    window.model.core_data_loaded.connect(lambda: loaded.append(1))
    path = tmp_path / "core.csv"
    path.write_text("Well,Depth (m),Porosity,Permeability\n"
                    "BKS-03,310,0.20,15\nBKS-03,315,0.22,30\nBKS-01,312,0.18,8\n")
    window._import_multi_well("core", str(path))
    active = well(window, "BKS-03")
    assert len(loaded) == 1
    assert active.core_depth_unit == "M" and active.core_import["depth_unit"] == "M"
    assert active.core_data.data[active.core_data.depth_col].iloc[0] == pytest.approx(310 * 3.28084)
    assert window.params_window.core_unit_combo.isEnabled()
    assert window.banner.message_label.text().startswith("Core data assigned to 2 wells")


def test_core_uses_the_core_matching_setting_when_the_file_has_no_unit(three_wells, tmp_path, dialogs):
    window = three_wells
    window.params_window.core_unit_combo.setCurrentText("M")
    path = tmp_path / "core.csv"
    path.write_text("Well,Depth,Porosity\nBKS-03,310,0.20\nBKS-03,315,0.22\n")
    window._import_multi_well("core", str(path))
    assert dialogs.seen[0].plan.effective_unit == "M"
    assert well(window, "BKS-03").core_depth_unit == "M"
