"""Optional well column in tops/core files, well matching and depth coverage (spec §5.3)."""

import io

from modules.core_handler import CoreDataHandler
from modules.formation_tops import FormationTops
from modules.well_matching import assign_to_wells, depth_coverage_warning

WELLS = [
    ("WELL:BKS-01", {"well_name": "BKS-01"}),
    ("WELL:BKS-02", {"well_name": "BKS-02"}),
]


def _tops(text):
    tops = FormationTops()
    assert tops.read_tops_from_buffer(io.StringIO(text))
    return tops


def _core(text, **kwargs):
    core = CoreDataHandler()
    assert core.read_core_from_buffer(io.StringIO(text), **kwargs)
    return core


TOPS_MULTI = (
    "Well\tFormation\tTop (ft)\tBottom (ft)\n"
    "BKS 01\tUpper\t1000\t1040\n"
    "BKS 01\tLower\t1040\t1100\n"
    "bks_02\tUpper\t1010\t\n"
    "bks_02\tLower\t1060\t1120\n"
    "OTHER-9\tUpper\t900\t950\n"
)


def test_tops_without_well_column_unchanged():
    tops = _tops("Formation\tTop (ft)\tBottom (ft)\nUpper\t1000\t1040\nLower\t1040\t1100\n")
    assert tops.well_names() == [] and tops.split_by_well() == {}
    assert [f.name for f in tops.formations] == ["Upper", "Lower"]
    assert tops.well_column is None


def test_tops_split_by_well():
    tops = _tops(TOPS_MULTI)
    # Wells come in the order of their shallowest top (formations are depth-sorted).
    assert tops.well_names() == ["OTHER-9", "BKS 01", "bks_02"]
    parts = tops.split_by_well()
    assert list(parts) == tops.well_names()
    assert [(f.name, f.top_depth) for f in parts["BKS 01"].formations] == [("Upper", 1000), ("Lower", 1040)]
    # A missing bottom is filled from the next top of the SAME well.
    assert parts["bks_02"].formations[0].bottom_depth == 1060
    assert parts["bks_02"].depth_unit == tops.depth_unit == "FT"
    assert parts["bks_02"].depth_unit_detected


def test_tops_well_name_column_is_not_the_formation_name():
    tops = _tops("WELL_NAME\tName\tTop (ft)\nW1\tUpper\t10\nW1\tLower\t20\n")
    assert [f.name for f in tops.formations] == ["Upper", "Lower"]
    assert tops.well_names() == ["W1"]


def test_tops_uwi_column_kind():
    tops = _tops("UWI\tFormation\tTop (m)\n42-001\tUpper\t100\n")
    assert tops.well_kind == "uwi" and tops.well_names() == ["42-001"]


def test_assign_to_wells_name_variants_and_unmatched():
    parts = _tops(TOPS_MULTI).split_by_well()
    assert list(parts) == ["OTHER-9", "BKS 01", "bks_02"]
    matches, unmatched = assign_to_wells(parts, WELLS)
    assert set(matches) == {"WELL:BKS-01", "WELL:BKS-02"}
    assert matches["WELL:BKS-01"] is parts["BKS 01"]
    assert matches["WELL:BKS-02"] is parts["bks_02"]
    assert unmatched == ["OTHER-9"]


def test_assign_to_wells_by_uwi_and_api():
    wells = [("UWI:42-001", {"uwi": "42-001", "well_name": "A"}), ("W:B", {"api": "7-7", "well_name": "B"})]
    matches, unmatched = assign_to_wells({"42-001": 1, "7-7": 2, "zz": 3}, wells, "uwi")
    assert matches == {"UWI:42-001": 1} and "zz" in unmatched
    matches, _ = assign_to_wells({"7-7": 2}, wells, "api")
    assert matches == {"W:B": 2}


def test_assign_to_wells_each_well_matched_once():
    matches, unmatched = assign_to_wells({"BKS-01": 1, "bks 01": 2}, WELLS)
    assert matches == {"WELL:BKS-01": 1} and unmatched == ["bks 01"]


CORE_MULTI = (
    "Well\tDepth (ft)\tPorosity (%)\tPerm (md)\n"
    "BKS-01\t1005\t12\t5\n"
    "BKS-01\t1010\t14\t8\n"
    "BKS 02\t1020\t18\t40\n"
    "Z-9\t1030\t10\t1\n"
)


def test_core_without_well_column_unchanged():
    core = _core("Depth (ft)\tPorosity (%)\tPerm (md)\n1005\t12\t5\n")
    assert core.well_col is None and core.well_names() == [] and core.split_by_well() == {}
    assert len(core.data) == 1 and core.get_summary()["n_samples"] == 1


def test_core_split_and_match():
    core = _core(CORE_MULTI)
    assert core.well_names() == ["BKS-01", "BKS 02", "Z-9"]
    parts = core.split_by_well()
    assert all(isinstance(p, CoreDataHandler) for p in parts.values())
    assert [len(p.data) for p in parts.values()] == [2, 1, 1]
    assert parts["BKS-01"].get_summary()["n_samples"] == 2
    assert parts["BKS-01"].depth_unit == core.depth_unit
    assert parts["BKS-01"].depth_col == core.depth_col
    matches, unmatched = assign_to_wells(parts, WELLS, core.well_kind)
    assert set(matches) == {"WELL:BKS-01", "WELL:BKS-02"} and unmatched == ["Z-9"]
    assert len(core.data) == 4  # the source is untouched


def test_core_meters_converted_once_before_split():
    core = _core("Well\tDepth (m)\tPorosity\nA\t100\t0.1\nB\t200\t0.2\n")
    parts = core.split_by_well()
    assert abs(parts["A"].data[core.depth_col].iloc[0] - 328.084) < 0.01
    assert parts["A"].converted_to_feet


def test_depth_coverage_warning():
    assert depth_coverage_warning("Upper", 1010, 1040, 1000, 1100) is None
    assert "entirely outside" in depth_coverage_warning("Upper", 900, 950, 1000, 1100)
    assert "entirely outside" in depth_coverage_warning("Upper", 1200, 1250, 1000, 1100)
    assert "extends beyond" in depth_coverage_warning("Lower", 1080, 1150, 1000, 1100)
    assert "extends beyond" in depth_coverage_warning("Lower", 990, 1050, 1000, 1100)
    assert depth_coverage_warning("X", None, 1, 0, 2) is None
    assert depth_coverage_warning("X", float("nan"), 1, 0, 2) is None
