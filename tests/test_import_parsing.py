"""Parsing of tops/core tables: delimiters, decimals, aliases, per-well handling.

One named test per defect found by the multi-well follow-up research
(P1-P9) plus tests for the reader features (preamble, unit row, xlsx, ...).
"""
import io

import pytest

from modules.core_handler import CoreDataHandler
from modules.formation_tops import FormationTops


def _tops(text, **kw):
    tops = FormationTops()
    ok = tops.read_tops_from_buffer(io.StringIO(text), **kw)
    assert ok, tops.last_error
    return tops


def _core(text, **kw):
    core = CoreDataHandler()
    assert core.read_core_from_buffer(io.StringIO(text), **kw)
    return core


# ---------------------------------------------------------------------------
# P1-P9
# ---------------------------------------------------------------------------
def test_p1_comma_tops():
    tops = _tops("Well,Formation,Top (m),Bottom (m)\nA,X,1,2\n")
    assert tops.well_names() == ["A"]
    fm = tops.formations[0]
    assert (fm.name, fm.top_depth, fm.bottom_depth) == ("X", 1.0, 2.0)
    assert tops.depth_unit == "M" and tops.depth_unit_detected


def test_p2_comma_core():
    core = _core("Well,Depth (ft),Porosity\nA,100,0.2\n")
    assert core.well_names() == ["A"]
    _, por = core.get_core_porosity()
    assert por[0] == pytest.approx(0.2)


def test_p3_porosity_scale_per_well():
    core = _core("Well\tDepth (ft)\tPorosity\nA\t100\t20\nB\t200\t0.2\n")
    parts = core.split_by_well()
    assert parts["A"].get_core_porosity()[1][0] == pytest.approx(0.20)
    assert parts["B"].get_core_porosity()[1][0] == pytest.approx(0.20)
    assert parts["A"].porosity_scale == "percent"
    assert parts["B"].porosity_scale == "fraction"
    assert core.porosity_scale_mixed
    assert core.porosity_warning


def test_p3_scale_override_and_invalid_values():
    core = _core("Well\tDepth (ft)\tPorosity\nA\t100\t20\nA\t110\t150\nB\t200\t0.2\n")
    a = core.split_by_well()["A"]
    por = a.get_core_porosity()[1]
    assert len(por) == 1 and por[0] == pytest.approx(0.2)  # 150 % is invalid
    assert any("150" in reason for _, reason in core.excluded_rows)
    b = core.split_by_well()["B"]
    b.set_porosity_scale("percent")  # user override: 0.2 % -> 0.002
    assert b.get_core_porosity()[1][0] == pytest.approx(0.002)
    assert b.porosity_scale == "percent"


def test_p4_blank_well_cells_counted():
    text = "Well\tFormation\tTop (m)\nA\tX\t100\n\tY\t200\nB\tX\t150\n"
    tops = _tops(text)
    assert tops.well_names() == ["A", "B"]
    assert tops.blank_well_rows == [3]
    line, reason = tops.excluded_rows[0]
    assert line == 3 and reason.startswith("no well")
    parts = tops.split_by_well()
    assert [f.name for f in parts["A"].formations] == ["X"]

    filled = _tops(text, fill_down=True)
    assert filled.blank_well_rows == []
    parts = filled.split_by_well()
    assert [f.name for f in parts["A"].formations] == ["X", "Y"]
    assert filled.fill_down_applicable
    assert filled.filled_rows == [3]


def test_p4_blank_well_cells_counted_core():
    core = _core("Well\tDepth (ft)\tPorosity\nA\t100\t0.2\n\t110\t0.21\nB\t200\t0.2\n")
    assert core.blank_well_rows == [3]
    assert len(core.split_by_well()["A"].data) == 1
    core = _core("Well\tDepth (ft)\tPorosity\nA\t100\t0.2\n\t110\t0.21\nB\t200\t0.2\n",
                 fill_down=True)
    assert len(core.split_by_well()["A"].data) == 2


def test_p5_name_spellings_grouped():
    tops = _tops("Well\tFormation\tTop (ft)\nBKS-01\tX\t100\nBKS 01\tY\t200\n")
    parts = tops.split_by_well(group=True)
    assert len(parts) == 1
    (key, part), = parts.items()
    assert sorted(part.spellings) == ["BKS 01", "BKS-01"]
    assert [f.name for f in part.formations] == ["X", "Y"]
    assert len(tops.split_by_well()) == 2  # old behaviour is still available


def test_p5_core_spellings_grouped_and_resorted():
    core = _core("Well\tDepth (ft)\tPorosity\nBKS-01\t300\t0.1\nBKS 01\t100\t0.2\n")
    parts = core.split_by_well(group=True)
    assert len(parts) == 1
    part = next(iter(parts.values()))
    assert list(part.data[core.depth_col]) == [100, 300]
    assert len(part.spellings) == 2


def test_p6_last_formation_bottom():
    tops = _tops("Well\tFormation\tTop (ft)\nA\tX\t100\nA\tY\t200\n")
    x, y = tops.formations
    assert x.bottom_depth == 200 and y.bottom_depth == 200  # parser output unchanged
    assert y.bottom_inferred and x.bottom_inferred
    explicit = _tops("Formation\tTop (ft)\tBottom (ft)\nX\t100\t150\n")
    assert not explicit.formations[0].bottom_inferred


def test_p7_petrel_surface_md():
    tops = _tops("Well\tSurface\tMD\nA\tX\t100\n")
    fm = tops.formations[0]
    assert (fm.name, fm.top_depth, fm.well) == ("X", 100.0, "A")


def test_p7_md_never_used_as_bottom_when_top_exists():
    tops = _tops("Well\tHorizon\tTop MD\tBottom MD\nA\tX\t100\t150\n")
    fm = tops.formations[0]
    assert (fm.top_depth, fm.bottom_depth) == (100.0, 150.0)


def test_p8_semicolon_decimal_comma():
    tops = _tops("Well;Formation;Top (m)\nA;X;1000,5\n")
    assert tops.formations[0].top_depth == pytest.approx(1000.5)
    assert tops.table_read.decimal == "," and tops.table_read.delimiter == ";"


def test_p9_core_tvd_depth_warns():
    core = _core("Well\tTVD (ft)\tPorosity\nA\t100\t0.2\n")
    assert core.depth_is_tvd
    assert "TVD" in core.tvd_warning
    plain = _core("Well\tDepth (ft)\tPorosity\nA\t100\t0.2\n")
    assert not plain.depth_is_tvd and plain.tvd_warning is None


# ---------------------------------------------------------------------------
# Reader features
# ---------------------------------------------------------------------------
def test_preamble_and_comment_lines():
    text = ("# exported by tool\n# project X\n\n"
            "Formation\tTop (m)\tBottom (m)\n# inline note\nA\t1\t2\nB\t2\t3\n")
    tops = _tops(text)
    assert [f.name for f in tops.formations] == ["A", "B"]
    assert tops.table_read.skipped_lines == 3


def test_preamble_text_rows_before_header():
    text = "Report of tops\nField: Z\nWell\tFormation\tTop (m)\nA\tX\t5\n"
    tops = _tops(text)
    assert tops.table_read.skipped_lines == 2
    assert tops.formations[0].top_depth == 5


def test_unit_row_dropped_and_feeds_unit_detection():
    tops = _tops("Formation\tTop\tBottom\nm\tm\tm\nA\t1000\t1100\nB\t1100\t1200\n")
    assert [f.name for f in tops.formations] == ["A", "B"]
    assert tops.depth_unit == "M" and tops.depth_unit_detected
    assert tops.depth_unit_warning is None
    assert tops.table_read.unit_row_unit == "M"
    assert tops.excluded_rows == []

    core = _core("Depth\tPorosity\nft\tfraction\n100\t0.2\n110\t0.21\n")
    assert core.depth_unit == "FT" and core.depth_unit_detected
    assert len(core.data) == 2


def test_column_name_unit_beats_unit_row():
    tops = _tops("Formation\tTop (ft)\nm\tm\nA\t1000\n")
    assert tops.depth_unit == "FT"


def test_tab_with_decimal_comma():
    core = _core("Well\tDepth (ft)\tPorosity\nA\t100,5\t0,2\nA\t101,5\t0,25\n")
    assert core.get_core_depths()[0] == pytest.approx(100.5)
    assert core.get_core_porosity()[1][1] == pytest.approx(0.25)
    assert core.table_read.decimal == "," and core.table_read.delimiter == "\t"


def test_dot_decimals_in_comma_file_untouched():
    tops = _tops("Formation,Top (m),Bottom (m)\nA,1000.5,1100.25\n")
    assert tops.formations[0].bottom_depth == pytest.approx(1100.25)


def test_bom_and_cp1252_paths(tmp_path):
    p = tmp_path / "tops_bom.csv"
    p.write_bytes("﻿Formation,Top (m)\nA,1\n".encode("utf-8"))
    tops = FormationTops()
    assert tops.read_tops_file(str(p))
    assert tops.formations[0].name == "A" and tops.table_read.encoding == "utf-8-sig"

    q = tmp_path / "tops_1252.txt"
    q.write_bytes("Formation\tTop (m)\nC\xf4te\t1\n".encode("cp1252"))
    tops = FormationTops()
    assert tops.read_tops_file(str(q))
    assert tops.formations[0].name == "C\xf4te" and tops.table_read.encoding == "cp1252"


def test_failure_lists_columns_each_attempt_found():
    tops = FormationTops()
    assert not tops.read_tops_from_buffer(io.StringIO("Foo,Bar\n1,2\n"))
    assert "Foo" in tops.last_error and "comma" in tops.last_error


def test_xlsx_with_sheets(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Notes"
    ws.append(["nothing here"])
    ws2 = wb.create_sheet("Tops")
    ws2.append(["Well", "Surface", "Top (m)", "Bottom (m)"])
    ws2.append(["A", "X", 100.5, 200])
    ws2.append(["A", "Y", 200, 300])
    path = tmp_path / "tops.xlsx"
    wb.save(path)

    from modules.table_reader import list_sheets
    assert list_sheets(str(path)) == ["Notes", "Tops"]
    tops = FormationTops()
    assert tops.read_tops_file(str(path), sheet="Tops"), tops.last_error
    assert [f.name for f in tops.formations] == ["X", "Y"]
    assert tops.formations[0].top_depth == pytest.approx(100.5)
    assert tops.table_read.sheet == "Tops"
    # the default (first) sheet has no tops columns
    assert not FormationTops().read_tops_file(str(path))


def test_non_numeric_depths_counted_with_line_numbers():
    tops = _tops("Formation\tTop (m)\nA\t1\nBad\tabc\nB\t3\n")
    assert [f.name for f in tops.formations] == ["A", "B"]
    assert [ln for ln, _ in tops.excluded_rows] == [3]
    core = _core("Depth (ft)\tPorosity\n100\t0.2\nx\t0.3\n120\t0.25\n")
    assert [ln for ln, _ in core.excluded_rows] == [3]
    assert len(core.data) == 2


def test_reversed_top_bottom_counted():
    tops = _tops("Formation\tTop (m)\tBottom (m)\nA\t1100\t1000\nB\t1\t2\n")
    assert tops.swapped_rows == [2]


def test_existing_tab_file_parses_as_before():
    tops = _tops("Stratigraphical unit\tTop (m)\tBottom (m)\tAnomaly code\n"
                 "A\t1000\t1100\tk1\nB\t1100\t1200\t\n")
    assert [(f.name, f.anomaly_code) for f in tops.formations] == [("A", "k1"), ("B", "")]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def test_fill_down_helper():
    from modules.well_matching import merged_cell_pattern_applies
    nan = float("nan")
    assert merged_cell_pattern_applies(["A", None, "", "B", None], [1, 2, 3, 1, 2])
    # first row without a well
    assert not merged_cell_pattern_applies([None, "A", "B"], [1, 2, 3])
    # well reappears after another well started: not contiguous
    assert not merged_cell_pattern_applies(["A", "B", None, "A"], [1, 2, 3, 4])
    # depths go back inside a block
    assert not merged_cell_pattern_applies(["A", None, None], [1, 3, 2])
    # no blanks: nothing to fill
    assert not merged_cell_pattern_applies(["A", "A"], [1, 2])
    assert merged_cell_pattern_applies(["A", None], [1, nan])


def test_group_well_names():
    from modules.well_matching import group_well_names
    groups = group_well_names(["BKS-01", "BKS 01", "bks_01", "Z-9"], "name")
    assert sorted(len(v) for v in groups.values()) == [1, 3]
    assert groups["BKS-01"] == ["BKS-01", "BKS 01", "bks_01"]
    api = group_well_names(["49-025-12345", "490251234500"], "api")
    assert len(api) == 2  # different numbers stay apart
    api = group_well_names(["49-025-12345", "4902512345"], "api")
    assert len(api) == 1


def test_extend_last_bottom():
    from modules.formation_tops import extend_last_bottom
    tops = _tops("Well\tFormation\tTop (ft)\nA\tX\t100\nA\tY\t200\nB\tX\t100\nB\tY\t5000\n")
    n = extend_last_bottom(tops, 1000.0)
    by = {(f.well, f.name): f for f in tops.formations}
    assert by[("A", "Y")].bottom_depth == 1000 and by[("A", "Y")].thickness == 800
    assert by[("A", "X")].bottom_depth == 200  # not the last one
    assert by[("B", "Y")].bottom_depth == 5000  # log bottom not deeper: unchanged
    assert n == 1

    explicit = _tops("Formation\tTop (ft)\tBottom (ft)\nX\t100\t150\n")
    assert extend_last_bottom(explicit, 9999.0) == 0
    assert explicit.formations[0].bottom_depth == 150


# ---------------------------------------------------------------------------
# Review fixes
# ---------------------------------------------------------------------------
def test_thousands_separator_is_not_read_as_decimal_comma():
    tops = _tops("Formation\tTop (ft)\tBottom (ft)\nX\t1,250\t1,300\nY\t1,300\t1,420\n")
    assert [f.top_depth for f in tops.formations] == [1250.0, 1300.0]
    assert any("thousands" in note for note in tops.notes)


def test_one_unambiguous_decimal_comma_decides_for_the_file():
    core = _core("Depth (ft)\tPorosity\tPermeability\n1,250\t0,215\t12,5\n")
    assert core.data["depth (ft)"].iloc[0] == pytest.approx(1.25)
    assert core.get_core_porosity()[1][0] == pytest.approx(0.215)


def test_one_percent_typo_does_not_rescale_a_fraction_well():
    core = _core("Depth (ft)\tPorosity\n100\t0.20\n101\t0.22\n102\t25\n103\t0.18\n")
    assert core.porosity_scale == "fraction"
    assert list(core.get_core_porosity()[1]) == pytest.approx([0.20, 0.22, 0.18])
    assert any("25" in reason for _, reason in core.excluded_rows)


def test_missing_sheet_index_is_a_clear_error(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    wb.active.append(["Formation", "Top (ft)"])
    path = tmp_path / "one.xlsx"
    wb.save(path)
    tops = FormationTops()
    assert not tops.read_tops_file(str(path), sheet=3)
    assert "Sheet 3 not found" in tops.last_error
