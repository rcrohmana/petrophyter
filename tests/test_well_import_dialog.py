"""MultiWellImportDialog: pre-filled mapping, defaults, OK rules, re-parse on change (spec 3.8)."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from modules.well_import import ImportOptions, WellRef
from ui.widgets.well_import_dialog import MultiWellImportDialog


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A modal box would block the offscreen test run; fail loudly instead."""
    from PyQt6.QtWidgets import QMessageBox

    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected dialog: {args[1:3]}")

    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


def write(tmp_path, text, name="tops.csv"):
    path = tmp_path / name
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return str(path)


def ref(name, **kw):
    kw.setdefault("log_top", 0.0)
    kw.setdefault("log_bottom", 10000.0)
    return WellRef(key=f"WELL:{name}", display_name=name, well_info={"well_name": name}, **kw)


def pick(combo, data):
    """Choose ``data`` in a combo the way a user does (fires ``activated``)."""
    index = combo.findData(data)
    assert index >= 0, f"{data!r} not in combo"
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


def make(qtbot, path, wells, kind="tops", **opts):
    dialog = MultiWellImportDialog(kind, path, wells, options=ImportOptions(kind=kind, **opts))
    qtbot.addWidget(dialog)
    return dialog


TOPS = """
Well,Surface,MD,Bottom (ft),Pick2 (ft)
BKS-01,A,1000,1100,1010
BKS-01,B,1100,1200,1110
BKS-02,A,2000,2100,2010
"""


def test_mapping_is_prefilled_from_detection(qtbot, tmp_path):
    dialog = make(qtbot, write(tmp_path, TOPS), [ref("BKS-01"), ref("BKS-02")])
    combos = dialog._column_combos
    assert combos["well"].currentData() == "Well"
    assert combos["name"].currentData() == "Surface"
    assert combos["top"].currentData() == "MD"
    assert combos["bottom"].currentData() == "Bottom (ft)"
    assert "comma" in dialog.file_label.text() and "UTF-8" in dialog.file_label.text()
    assert dialog.table.rowCount() == 2
    assert dialog.table.item(0, dialog._col["File well"]).text() == "BKS-01"
    # The preview shows the first rows of the selected well with the mapped role per column.
    header = dialog.preview.horizontalHeaderItem(2).text()
    assert header.startswith("Top") and "MD" in header
    assert dialog.preview.rowCount() == 2


def test_changing_a_column_combo_reparses(qtbot, tmp_path):
    dialog = make(qtbot, write(tmp_path, TOPS), [ref("BKS-01"), ref("BKS-02")])
    before = dialog.plan.rows[0].depth_range
    assert before == (1000.0, 1200.0)
    pick(dialog._column_combos["top"], "Pick2 (ft)")
    assert dialog.options.columns["top"] == "Pick2 (ft)"
    assert dialog.plan.rows[0].depth_range == (1010.0, 1200.0)
    assert dialog._column_combos["top"].currentData() == "Pick2 (ft)"


def test_a_column_choice_that_breaks_the_file_is_reverted_with_a_message(qtbot, tmp_path):
    dialog = make(qtbot, write(tmp_path, TOPS), [ref("BKS-01"), ref("BKS-02")])
    pick(dialog._column_combos["well"], None)
    assert "well column" in dialog.message_label.text()
    assert dialog._column_combos["well"].currentData() == "Well"
    assert dialog.plan.rows and dialog.ok_button.isEnabled()


def test_keep_or_replace_default_follows_the_source_file(qtbot, tmp_path):
    path = write(tmp_path, TOPS)
    wells = [ref("BKS-01", existing_count=3, existing_path=path),      # same file: re-import
             ref("BKS-02", existing_count=2, existing_path="C:/other/tops.txt")]
    dialog = make(qtbot, path, wells)
    first, second = dialog._action_combos
    assert first.currentData() == "replace" and second.currentData() == "keep"
    assert [first.itemData(i) for i in range(first.count())] == ["keep", "replace"]
    assert dialog.ok_button.text() == "Assign to 1 well"
    pick(second, "replace")
    assert dialog.plan.rows[1].action == "replace"
    assert dialog.ok_button.text() == "Assign to 2 wells"


def test_an_empty_well_is_assigned_and_its_action_is_fixed(qtbot, tmp_path):
    dialog = make(qtbot, write(tmp_path, TOPS), [ref("BKS-01"), ref("BKS-02")])
    for combo in dialog._action_combos:
        assert combo.currentData() == "assign" and not combo.isEnabled()
    assert dialog.not_in_file_label.text() == ""


def test_ok_needs_a_depth_unit_when_the_file_has_none(qtbot, tmp_path):
    text = "Well,Formation,Top,Bottom\nBKS-01,A,1000,1100\nBKS-02,A,2000,2100\n"
    dialog = make(qtbot, write(tmp_path, text), [ref("BKS-01"), ref("BKS-02")])
    assert not dialog.ok_button.isEnabled()
    assert "depth unit" in dialog.ok_button.toolTip()
    pick(dialog.unit_combo, "FT")
    assert dialog.ok_button.isEnabled() and dialog.ok_button.toolTip() == ""
    assert dialog.plan.effective_unit == "FT"
    pick(dialog.unit_combo, "M")
    assert dialog.plan.rows[0].depth_range[0] == pytest.approx(1000 * 3.28084)


def test_ambiguous_match_and_shared_target_disable_ok_with_a_reason(qtbot, tmp_path):
    twins = [ref("BKS-01"), WellRef(key="WELL:BKS-01#2", display_name="BKS-01",
                                    well_info={"well_name": "BKS-01"},
                                    log_top=0.0, log_bottom=10000.0), ref("BKS-02")]
    dialog = make(qtbot, write(tmp_path, TOPS), twins)
    assert not dialog.ok_button.isEnabled()
    assert "Choose the well for BKS-01" in dialog.ok_button.toolTip()
    pick(dialog._match_combos[0], "WELL:BKS-01#2")
    assert dialog.ok_button.isEnabled()
    pick(dialog._match_combos[1], "WELL:BKS-01#2")       # two file wells, one loaded well
    assert not dialog.ok_button.isEnabled()
    assert "same well" in dialog.ok_button.toolTip()
    pick(dialog._match_combos[1], None)
    assert dialog.ok_button.isEnabled()
    assert dialog.plan.rows[1].action == "skip"


def test_ok_is_disabled_when_nothing_would_change(qtbot, tmp_path):
    dialog = make(qtbot, write(tmp_path, TOPS), [ref("OTHER")])
    assert not dialog.ok_button.isEnabled()
    assert "No well would receive data" in dialog.ok_button.toolTip()
    assert dialog.not_in_file_label.text() == "Loaded wells not in this file: OTHER"


def test_cancel_leaves_the_plan_inputs_alone(qtbot, tmp_path):
    wells = [ref("BKS-01", existing_count=3), ref("BKS-02")]
    dialog = make(qtbot, write(tmp_path, TOPS), wells)
    dialog.reject()
    assert dialog.result() == 0
    assert [(w.existing_count, w.existing_path) for w in wells] == [(3, None), (0, None)]


def test_fill_down_is_ticked_for_merged_cells_and_can_be_switched_off(qtbot, tmp_path):
    text = ("Well,Formation,Top (ft),Bottom (ft)\n"
            "BKS-01,A,1000,1100\n,B,1100,1200\nBKS-02,A,2000,2100\n,B,2100,2200\n")
    dialog = make(qtbot, write(tmp_path, text), [ref("BKS-01"), ref("BKS-02")])
    assert dialog.fill_check.isChecked()
    assert [r.rows for r in dialog.plan.rows] == [2, 2]
    dialog.fill_check.setChecked(False)
    dialog.fill_check.clicked.emit(False)
    assert [r.rows for r in dialog.plan.rows] == [1, 1]
    assert len(dialog.plan.no_well_rows) == 2
    assert "without a well" in dialog.message_label.text()


def test_core_porosity_scale_is_shown_per_well_and_can_be_overridden(qtbot, tmp_path):
    text = ("Well,Depth (ft),Porosity,Permeability\n"
            "BKS-01,1000,20,15\nBKS-01,1010,22,30\nBKS-02,2000,0.18,8\nBKS-02,2010,0.2,9\n")
    dialog = make(qtbot, write(tmp_path, text, "core.csv"), [ref("BKS-01"), ref("BKS-02")],
                  kind="core")
    first, second = dialog._scale_combos
    assert first.currentData() == "percent" and second.currentData() == "fraction"
    assert "scale" in dialog.message_label.text().lower() or dialog.plan.notes
    pick(second, "percent")
    assert dialog.plan.rows[1].porosity_scale == "percent"
    assert dialog.options.porosity_scales == {"BKS-02": "percent"}


def test_core_tvd_depth_needs_a_confirmation(qtbot, tmp_path):
    text = "Well,TVD (ft),Porosity\nBKS-01,1000,0.2\nBKS-01,1010,0.22\n"
    dialog = make(qtbot, write(tmp_path, text, "core.csv"), [ref("BKS-01")], kind="core")
    assert dialog.tvd_check.isVisibleTo(dialog)
    assert not dialog.ok_button.isEnabled()
    assert "TVD" in dialog.ok_button.toolTip()
    dialog.tvd_check.setChecked(True)
    dialog.tvd_check.clicked.emit(True)
    assert dialog.ok_button.isEnabled()


def test_a_file_without_a_well_column_is_refused(qtbot, tmp_path):
    path = write(tmp_path, "Formation,Top (ft),Bottom (ft)\nA,1000,1100\n")
    with pytest.raises(ValueError, match="no well column"):
        MultiWellImportDialog("tops", path, [ref("BKS-01")])


def test_sheet_combo_appears_for_workbooks_with_several_sheets(qtbot, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    one = book.active
    one.title = "First"
    one.append(["Well", "Formation", "Top (ft)", "Bottom (ft)"])
    one.append(["BKS-01", "A", 1000, 1100])
    two = book.create_sheet("Second")
    two.append(["Well", "Formation", "Top (ft)", "Bottom (ft)"])
    two.append(["BKS-01", "A", 1500, 1600])
    path = str(tmp_path / "tops.xlsx")
    book.save(path)
    dialog = make(qtbot, path, [ref("BKS-01")])
    assert dialog.sheet_combo.isVisibleTo(dialog) and dialog.sheet_combo.count() == 2
    assert dialog.plan.rows[0].depth_range == (1000.0, 1100.0)
    pick(dialog.sheet_combo, "Second")
    assert dialog.plan.rows[0].depth_range == (1500.0, 1600.0)
